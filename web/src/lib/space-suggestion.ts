/**
 * The space Lekto suggests for a document (the judge's open `space` check): which one, its
 * name, who sees the document there that does not see it now, and whom the document names who
 * would not see it there (`unseen_by`).
 */
import type { components } from '#lib/api/schema.ts';
import { describeValue } from '#lib/describe.ts';
import { userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

type OpenNode = components['schemas']['OpenNodeOut'];
type NodeReview = components['schemas']['NodeReviewOut'];

/** The suggested space of the open fields: the first open `space` check with a suggestion. */
export function suggestedSpace(open: readonly OpenNode[]): string | null {
	for (const node of open) {
		for (const check of node.fields) {
			if (check.field === 'space' && typeof check.suggestion === 'string') return check.suggestion;
		}
	}
	return null;
}

/** Whether the only open point is the suggested space (a failed node is one, without fields). */
export function onlySpace(open: readonly OpenNode[]): boolean {
	if (open.some((node) => node.outcome === 'failed')) return false;
	const fields = open.flatMap((node) => node.fields);
	return fields.length > 0 && fields.every((check) => check.field === 'space');
}

/** Whether the caller can tell which space `target` is: one of theirs, or a user's personal one. */
export function knownSpace(target: string, lookup: Lookup | null): boolean {
	if (!lookup) return false;
	return (
		lookup.spaces.some((space) => space.id === target) ||
		lookup.users.some((user) => user.personal_space_id === target)
	);
}

/** The members of `target` who are no members of `current`, by name; for another user's
 * personal space the caller is no member of, that user. Empty where the caller cannot tell. */
export function newReaders(target: string, current: string, lookup: Lookup | null): string[] {
	if (!lookup) return [];
	const there = lookup.spaces.find((space) => space.id === target);
	const here = lookup.spaces.find((space) => space.id === current);
	const already = new Set(here?.members.map((member) => member.user_id) ?? []);
	if (there) {
		return there.members
			.filter((member) => !already.has(member.user_id))
			.map((member) => userLabel(member));
	}
	const holder = lookup.users.find((user) => user.personal_space_id === target);
	return holder && !already.has(holder.id) ? [userLabel(holder)] : [];
}

/** The user `target` hands the document over to: whose personal space it is, if they are no
 * member of `current` (as far as the caller sees); null for any other space. */
export function handedTo(target: string, current: string, lookup: Lookup | null): string | null {
	const holder = lookup?.users.find((user) => user.personal_space_id === target);
	if (!holder) return null;
	const here = lookup?.spaces.find((space) => space.id === current);
	if (here?.members.some((member) => member.user_id === holder.id)) return null;
	return userLabel(holder);
}

/** The users the first open `space` check lists as named in the document but not seeing it
 * where the check leads. */
export function unseenBy(open: readonly OpenNode[]): string[] {
	for (const node of open) {
		for (const check of node.fields) {
			if (check.field === 'space' && check.unseen_by?.length) return check.unseen_by;
		}
	}
	return [];
}

/** Whom the document names who does not see it where it lies, from the judge's space check
 * when that settled without a person (it stays, or the judge moved it): those still no member
 * of `current`. The API names someone else only where the text has their display name. */
export function unseenHere(
	nodes: readonly NodeReview[],
	current: string,
	lookup: Lookup | null
): string[] {
	const check = nodes
		.find((node) => node.node === 'judge')
		?.fields.find((field) => field.field === 'space');
	if (!check || check.outcome !== 'ok' || !check.unseen_by?.length) return [];
	const here = lookup?.spaces.find((space) => space.id === current);
	return check.unseen_by.filter((id) => !here?.members.some((member) => member.user_id === id));
}

/** "Genannt, sieht es dort aber nicht: Anna Busch": those `ids` by name; someone the caller
 * cannot tell stays unnamed. Empty without any. */
export function unseenText(ids: readonly string[], lookup: Lookup | null): string {
	if (ids.length === 0) return '';
	const names = ids.map((id) => {
		const user = lookup?.users.find((entry) => entry.id === id);
		return user ? userLabel(user) : null;
	});
	const known = names.filter((name): name is string => name !== null);
	const listed = known.length < names.length ? [...known, m.space_named_someone()] : known;
	return m.space_named_unseen({ names: listed.join(', ') });
}

/** "Vorschlag: Haushalt (sichtbar für anna)": the suggested space and who sees it there anew;
 * another user's personal space as a hand-over ("Vorschlag: an Anna übergeben"); a space the
 * caller cannot see is not named (its id says nothing to them). */
export function suggestionText(target: string, current: string, lookup: Lookup | null): string {
	if (!knownSpace(target, lookup)) return m.space_suggestion({ space: m.space_unseen() });
	const receiver = handedTo(target, current, lookup);
	if (receiver) return m.space_suggestion_hand_over({ name: receiver });
	const space = describeValue(target, lookup);
	const names = newReaders(target, current, lookup);
	return names.length > 0
		? m.space_suggestion_for({ space, names: names.join(', ') })
		: m.space_suggestion({ space });
}
