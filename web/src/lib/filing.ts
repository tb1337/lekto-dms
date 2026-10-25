/**
 * The document's filing, the "Ablage" box of the document view (Tobi, 22.10.2026): where it
 * lies and who sees it, and, while the judge's space check waits for a person, the choices the
 * signals offer, each with what speaks for it and what it changes. A suggestion is chosen from
 * the start; a disagreement chooses nothing, the person decides.
 */
import type { components } from '#lib/api/schema.ts';
import { formatPercent } from '#lib/i18n.ts';
import { holderOf, spaceNameFor, userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { knownSpace, newReaders } from '#lib/space-suggestion.ts';

type OpenNode = components['schemas']['OpenNodeOut'];
type Check = components['schemas']['FieldCheckOut'];
type Source = components['schemas']['CandidateSourceOut'];
type Member = components['schemas']['SpaceOut']['members'][number];

/** The caller as the box needs them: who they are and whether admin rights let them see all. */
export interface Viewer {
	id: string | undefined;
	admin: boolean;
}

/** What a choice does: the document stays, moves into another space, or goes to another user. */
export type FilingKind = 'stay' | 'move' | 'hand_over';

export interface FilingChip {
	text: string;
	/** The signal is sure of the space: it counts for the judge. */
	strong: boolean;
}

export interface FilingOption {
	/** The space it leads to. */
	value: string;
	kind: FilingKind;
	title: string;
	chips: FilingChip[];
	/** What changes for whom. */
	consequence: string;
	/** The caller may put it there (a space they edit, a hand-over, or where it lies). */
	choosable: boolean;
	suggested: boolean;
}

export interface Filing {
	check: Check;
	suggestion: string | null;
	/** Several spaces named and none suggested: the signals disagree. */
	disagree: boolean;
	status: string;
	lead: string;
	options: FilingOption[];
}

/** The open `space` check among the open nodes; null without one. */
export function openSpaceCheck(open: readonly OpenNode[]): Check | null {
	for (const node of open) {
		const check = node.fields.find((field) => field.field === 'space');
		if (check) return check;
	}
	return null;
}

/** The user whose personal space `target` is, unless the caller is a member of it (then it is
 * one of their spaces); null for any other space. */
function receiverOf(target: string, lookup: Lookup, viewer: Viewer) {
	const holder = holderOf(lookup.users, target);
	if (!holder || holder.id === viewer.id) return null;
	const space = lookup.spaces.find((entry) => entry.id === target);
	if (space?.members.some((member) => member.user_id === viewer.id)) return null;
	return holder;
}

/** What leading the document to `target` does, seen from where it lies (`current`). */
export function filingKind(
	target: string,
	current: string,
	lookup: Lookup,
	viewer: Viewer
): FilingKind {
	if (target === current) return 'stay';
	return receiverOf(target, lookup, viewer) ? 'hand_over' : 'move';
}

/** The space's name for the caller; a space they cannot tell stays unnamed. */
export function spaceName(target: string, lookup: Lookup, viewer: Viewer): string {
	return spaceNameFor(target, lookup, viewer.id);
}

/** Whose personal space `target` is, by name, unless it is the caller's own; null for a shared
 * space. The space of another person reads as theirs: "Bei Anna Leider lassen", "Zu Anna Leider". */
function personOf(target: string, lookup: Lookup, viewer: Viewer): string | null {
	const holder = holderOf(lookup.users, target);
	return holder && holder.id !== viewer.id ? userLabel(holder) : null;
}

/** The members of `target` who are no members of `current`; empty where the caller cannot
 * tell. */
function lostReaders(target: string, current: string, lookup: Lookup): string[] {
	const there = lookup.spaces.find((space) => space.id === target);
	const here = lookup.spaces.find((space) => space.id === current);
	if (!there || !here) return [];
	const staying = new Set(there.members.map((member) => member.user_id));
	return here.members
		.filter((member) => !staying.has(member.user_id))
		.map((member) => userLabel(member));
}

/** What a choice reads as: "Übergeben an Anna Leider", "Nach Haushalt", "In Tobi lassen". */
export function choiceTitle(
	kind: FilingKind,
	target: string,
	lookup: Lookup,
	viewer: Viewer
): string {
	if (kind === 'hand_over') {
		const receiver = receiverOf(target, lookup, viewer);
		return m.move_hand_over({ name: receiver ? userLabel(receiver) : m.space_unseen() });
	}
	const person = personOf(target, lookup, viewer);
	if (kind === 'stay') {
		return person
			? m.filing_stay_with({ name: person })
			: m.filing_stay({ space: spaceName(target, lookup, viewer) });
	}
	if (person) return m.filing_move_person({ name: person });
	if (!knownSpace(target, lookup)) return m.filing_move_unseen();
	return m.filing_move({ space: spaceName(target, lookup, viewer) });
}

function consequence(
	kind: FilingKind,
	target: string,
	current: string,
	lookup: Lookup,
	viewer: Viewer
): string {
	if (kind === 'stay') return m.filing_stays();
	if (kind === 'hand_over') {
		const receiver = receiverOf(target, lookup, viewer);
		const name = receiver ? userLabel(receiver) : m.space_unseen();
		return viewer.admin
			? m.filing_hand_over_admin({ name })
			: m.filing_hand_over_consequence({ name });
	}
	const added = newReaders(target, current, lookup);
	const lost = lostReaders(target, current, lookup);
	const lines = [
		...(added.length > 0 ? [m.filing_new_readers({ names: added.join(', ') })] : []),
		...(lost.length > 0 ? [m.filing_lost_readers({ names: lost.join(', ') })] : [])
	];
	return lines.length > 0 ? lines.join(' ') : m.filing_same_readers();
}

/** What each signal says for a space, as chips: the model (and the recipient it read), the
 * similar documents that lie there, the classifier's probability. */
export function filingChips(
	sources: readonly Source[],
	lookup: Lookup,
	target: string
): FilingChip[] {
	const chips: FilingChip[] = [];
	for (const source of sources) {
		if (source.signal === 'signal_llm') {
			if (source.recipient) {
				const holder = holderOf(lookup.users, target);
				if (holder)
					chips.push({ text: m.filing_chip_recipient({ name: userLabel(holder) }), strong: true });
			}
			chips.push({ text: m.filing_chip_model(), strong: source.names });
		} else if (source.signal === 'signal_neighbours') {
			chips.push({
				text: m.filing_chip_neighbours({ votes: source.votes ?? 0, found: source.found ?? 0 }),
				strong: source.names
			});
		} else if (source.signal === 'signal_classifier') {
			chips.push({
				text: m.filing_chip_classifier({ score: formatPercent(source.score ?? 0) }),
				strong: source.names
			});
		}
	}
	return chips;
}

/**
 * The open filing for the caller: the suggestion first, the other spaces the signals name, and
 * staying where it lies; each with its chips and consequence. `choices` are the spaces the caller
 * may lead the document to (those they edit, and hand-overs).
 */
export function openFiling(
	check: Check,
	current: string,
	lookup: Lookup,
	viewer: Viewer,
	choices: readonly { value: string }[]
): Filing {
	const suggestion = typeof check.suggestion === 'string' ? check.suggestion : null;
	const candidates = (check.candidates ?? []).filter(
		(candidate): candidate is typeof candidate & { value: string } =>
			typeof candidate.value === 'string'
	);
	const order = [
		...(suggestion ? [suggestion] : []),
		...candidates.map((candidate) => candidate.value),
		current
	].filter((value, index, all) => all.indexOf(value) === index);
	const choosable = new Set([current, ...choices.map((choice) => choice.value)]);
	const options = order.map((value): FilingOption => {
		const kind = filingKind(value, current, lookup, viewer);
		const sources = candidates.find((candidate) => candidate.value === value)?.sources ?? [];
		return {
			value,
			kind,
			title: choiceTitle(kind, value, lookup, viewer),
			chips: filingChips(sources, lookup, value),
			consequence: consequence(kind, value, current, lookup, viewer),
			choosable: choosable.has(value),
			suggested: value === suggestion
		};
	});
	const named = new Set(candidates.map((candidate) => candidate.value));
	const disagree = suggestion === null && named.size > 1;
	const suggested = options.find((option) => option.suggested);
	let lead: string;
	if (suggested?.kind === 'hand_over') {
		const receiver = receiverOf(suggested.value, lookup, viewer);
		lead = m.filing_lead_hand_over({ name: receiver ? userLabel(receiver) : m.space_unseen() });
	} else if (suggested?.kind === 'move') {
		const person = personOf(suggested.value, lookup, viewer);
		lead = person
			? m.filing_lead_move_person({ name: person })
			: m.filing_lead_move({ space: spaceName(suggested.value, lookup, viewer) });
	} else if (disagree) lead = m.filing_lead_disagree();
	else lead = m.filing_lead_choose();
	return {
		check,
		suggestion,
		disagree,
		status: disagree ? m.filing_status_disagree() : m.filing_status_open(),
		lead,
		options
	};
}

/** The space chosen first: the suggestion, where the caller may take it; nothing otherwise
 * (a disagreement is the person's to decide). */
export function initialChoice(filing: Filing): string {
	const suggested = filing.options.find((option) => option.suggested && option.choosable);
	return suggested?.value ?? '';
}

/** The members who see the document besides the caller, by name: editors always, readers once
 * it is green; and the readers who see it once it is green. */
export function visibleNames(
	members: readonly Member[],
	viewer: Viewer,
	green: boolean
): { now: string[]; later: string[] } {
	const others = members.filter((member) => member.user_id !== viewer.id);
	return {
		now: others
			.filter((member) => member.role === 'edit' || green)
			.map((member) => userLabel(member)),
		later: green
			? []
			: others.filter((member) => member.role === 'read').map((member) => userLabel(member))
	};
}

/** "visible to Anna, Ben", or "visible to you only". */
export function visibleText(members: readonly Member[], viewer: Viewer, green: boolean): string {
	const { now } = visibleNames(members, viewer, green);
	return now.length > 0 ? m.visible_to({ names: now.join(', ') }) : m.visible_to_you();
}

/** "Anna reads it once it is green"; null when nobody waits for that. */
export function readersLaterText(
	members: readonly Member[],
	viewer: Viewer,
	green: boolean
): string | null {
	const { later } = visibleNames(members, viewer, green);
	return later.length > 0 ? m.visible_to_readers_later({ names: later.join(', ') }) : null;
}

/** "Liegt in Persönlich · nur für dich sichtbar". */
export function whereText(current: string, lookup: Lookup, viewer: Viewer, green: boolean): string {
	const space = lookup.spaces.find((entry) => entry.id === current);
	const visible = visibleText(space?.members ?? [], viewer, green);
	const person = personOf(current, lookup, viewer);
	return person
		? m.filing_where_person({ name: person, visible })
		: m.filing_where({ space: spaceName(current, lookup, viewer), visible });
}

/** A member of the space as a chip; `key` is the member's user id (two members may share a
 * display name). */
export interface MemberChip {
	key: string;
	text: string;
}

/** The members of the space as chips: the caller first ("Du · bearbeitest"), then the others
 * with their role; readers of a document that is not green yet see it once it is. */
export function memberChips(
	members: readonly Member[],
	viewer: Viewer,
	green: boolean
): MemberChip[] {
	const own = members.find((member) => member.user_id === viewer.id);
	const others = members.filter((member) => member.user_id !== viewer.id);
	return [
		...(own
			? [
					{
						key: own.user_id,
						text: own.role === 'edit' ? m.filing_you_edit() : m.filing_you_read()
					}
				]
			: []),
		...others.map((member) => ({
			key: member.user_id,
			text:
				member.role === 'edit'
					? m.filing_member_edit({ name: userLabel(member) })
					: green
						? m.filing_member_read({ name: userLabel(member) })
						: m.filing_member_read_later({ name: userLabel(member) })
		}))
	];
}

/** The line above "Confirm": choose first; what a hand-over or a move does; nothing when the
 * document stays. */
export function confirmHint(
	target: string,
	current: string,
	lookup: Lookup,
	viewer: Viewer
): { text: string; tone: 'warning' | 'hint' } | null {
	if (target === '') return { text: m.filing_choose_first(), tone: 'hint' };
	const kind = filingKind(target, current, lookup, viewer);
	if (kind === 'stay') return null;
	if (kind === 'hand_over') {
		const receiver = receiverOf(target, lookup, viewer);
		const name = receiver ? userLabel(receiver) : m.space_unseen();
		return {
			text: viewer.admin
				? m.filing_hint_hand_over_admin({ name })
				: m.filing_hint_hand_over({ name }),
			tone: 'warning'
		};
	}
	const added = newReaders(target, current, lookup);
	const names = added.join(', ');
	const person = personOf(target, lookup, viewer);
	if (person) {
		return {
			text:
				added.length > 0
					? m.filing_hint_move_person_readers({ name: person, names })
					: m.filing_hint_move_person({ name: person }),
			tone: 'hint'
		};
	}
	const space = spaceName(target, lookup, viewer);
	return {
		text:
			added.length > 0
				? m.filing_hint_move_readers({ space, names })
				: m.filing_hint_move({ space }),
		tone: 'hint'
	};
}
