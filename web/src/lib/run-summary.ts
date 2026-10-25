/**
 * A run at a glance, for the head of the processing view: one sentence where and why it stands
 * (it runs, stops before filing, failed, went through), what would help next, and what changed
 * since the run before.
 */
import type { components } from '#lib/api/schema.ts';
import { describeValue, fieldLabel } from '#lib/describe.ts';
import { choiceTitle, filingKind, type Viewer } from '#lib/filing.ts';
import { holderOf, userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { NODE_LABELS } from '#lib/node-labels.ts';
import { m } from '#lib/paraglide/messages.js';
import { labelled, reasonsText } from '#lib/reasons.ts';
import type { GraphNode, Node } from '#lib/pipeline.ts';
import { nodeRun, startedAgain } from '#lib/runs.ts';
import { list, object, person, text } from '#lib/signals.ts';
import { byPerson, confirmationOf } from '#lib/step-summary.ts';
import { stuck, type Step } from '#lib/steps.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];
type Json = Record<string, unknown>;

export type HeadlineTone = 'running' | 'yellow' | 'red' | 'green';

/** What helps next: the filing question or the review in the document tab, a reprocessing. */
export type HeadlineAction = 'filing' | 'review' | 'reprocess' | null;

export interface Headline {
	tone: HeadlineTone;
	title: string;
	/** Why, where there is more to say. */
	detail: string | null;
	action: HeadlineAction;
}

export interface ShownRun {
	number: number;
	/** The document's current run: what waits, waits for someone now. */
	current: boolean;
	status: ProcessingStatus;
}

const UNSURE = new Set(['uncertain', 'failed']);

const lastOf = (steps: readonly Step[], node: Node) =>
	steps.find((step) => step.node === node)?.done.entries.at(-1);

const checksOf = (entry: LogEntry | undefined): Json[] =>
	list(object(entry?.output).fields).map(object);

const names = (steps: readonly Step[]) => steps.map((step) => NODE_LABELS[step.node]()).join(', ');

/**
 * The sentence of a run: while it runs, where it is; stopped before filing, what is open (the
 * space with its suggestion, the fields) and why; failed, where and why; through, whether by
 * itself or after whom. `space`: where the document lies.
 */
export function headlineOf(
	run: ShownRun,
	steps: readonly Step[],
	space: string,
	lookup: Lookup | null,
	viewer: Viewer
): Headline {
	switch (run.status) {
		case 'processing': {
			const running = steps.filter((step) => step.state?.status === 'running');
			return {
				tone: 'running',
				title:
					running.length > 0
						? m.run_running_at({ run: run.number, steps: names(running) })
						: m.run_running({ run: run.number }),
				detail: null,
				action: null
			};
		}
		case 'review':
			return review(run, steps, space, lookup, viewer);
		case 'failed': {
			const failed = stuck(steps);
			const first = failed[0]?.done.entries.at(-1);
			return {
				tone: 'red',
				title: m.run_failed({ run: run.number, steps: names(failed) }),
				detail:
					first?.outcome === 'failed'
						? reasonsText(first.reasons, first.reason, labelled(lookup))
						: null,
				action: run.current ? 'reprocess' : null
			};
		}
		case 'completed':
			return { tone: 'green', title: through(run, steps, lookup), detail: null, action: null };
	}
}

function through(run: ShownRun, steps: readonly Step[], lookup: Lookup | null): string {
	const confirmed = steps.find((step) => step.overruled === 'confirmed')?.done.entries.at(-1);
	const confirmation = confirmed ? confirmationOf(confirmed) : null;
	if (confirmation) {
		const name = person(confirmation.by, lookup);
		return confirmation.before === 'failed'
			? m.run_through_decided({ run: run.number, name })
			: m.run_through_confirmed({ run: run.number, name });
	}
	if (steps.some((step) => step.overruled === 'settled')) {
		return m.run_through_settled({ run: run.number });
	}
	const own = steps.filter((step) => step.done.from === null);
	if (own.some((step) => step.done.entries.some(byPerson))) return m.run_done({ run: run.number });
	return m.run_through({ run: run.number });
}

function review(
	run: ShownRun,
	steps: readonly Step[],
	space: string,
	lookup: Lookup | null,
	viewer: Viewer
): Headline {
	const verdict = lastOf(steps, 'judge');
	const checks = [
		...checksOf(verdict),
		...checksOf(lastOf(steps, 'fields')),
		...checksOf(lastOf(steps, 'apply_rules'))
	].filter((check) => UNSURE.has(String(check.outcome)));
	const spaceCheck = checks.find((check) => check.field === 'space');
	// A review a rule forces is no field of the document: a sentence of its own.
	const ruleReview = checks.some((check) => check.field === 'review');
	const others = [
		...new Set(
			checks
				.filter((check) => check.field !== 'space' && check.field !== 'review')
				.map((check) => fieldLabel(String(check.field), lookup))
		)
	];
	const parts: string[] = [];
	if (spaceCheck) parts.push(...spaceWhy(spaceCheck, verdict, space, lookup, viewer));
	if (others.length > 0) parts.push(m.run_why_fields({ fields: others.join(', ') }));
	if (ruleReview) parts.push(m.run_why_rule_review());
	if (parts.length === 0) {
		const open = stuck(steps);
		if (open.length > 0) parts.push(m.run_why_fields({ fields: names(open) }));
	}
	return {
		tone: 'yellow',
		title: run.current ? m.run_review({ run: run.number }) : m.run_review_past({ run: run.number }),
		detail: parts.length > 0 ? parts.join(' ') : null,
		action: run.current ? (spaceCheck ? 'filing' : 'review') : null
	};
}

/** Why the space is open: the suggestion, the person the text names for it, who would not see
 * the document there. */
function spaceWhy(
	check: Json,
	verdict: LogEntry | undefined,
	space: string,
	lookup: Lookup | null,
	viewer: Viewer
): string[] {
	const suggestion = text(check.suggestion);
	const parts: string[] = [];
	if (suggestion && lookup) {
		const kind = filingKind(suggestion, space, lookup, viewer);
		parts.push(m.run_why_space({ choice: choiceTitle(kind, suggestion, lookup, viewer) }));
		const holder = holderOf(lookup.users, suggestion);
		const sure = list(object(verdict?.output).persons)
			.map(object)
			.some((found) => found.user_id === holder?.id && found.strength === 'hard');
		if (holder && holder.id !== viewer.id && sure) {
			parts.push(m.run_why_evidence({ name: userLabel(holder) }));
		}
	} else {
		parts.push(m.run_why_space_open());
	}
	const unseen = list(check.unseen_by).map((id) => person(id, lookup));
	if (unseen.length === 1) parts.push(m.run_why_unseen_one({ name: unseen[0] }));
	else if (unseen.length > 1) parts.push(m.run_why_unseen({ names: unseen.join(', ') }));
	return parts;
}

/** The fields whose decided value a later run may change, in the order they are told. */
const COMPARED = ['contact', 'document_type', 'topic', 'document_date', 'space'] as const;

export interface Changes {
	/** The run before the one shown. */
	since: number;
	items: string[];
}

/**
 * What changed in run `shown` against the run before it (of `runs`): the values the verdict
 * decided (contact, type, topic, date, space), how many field values differ, whether the
 * archive became PDF/A or stopped being one. Null without a run before or without a change; a
 * value that is open in either run is no change yet.
 */
export function changesOf(
	entries: readonly LogEntry[],
	graph: readonly GraphNode[],
	shown: number,
	runs: readonly number[],
	lookup: Lookup | null
): Changes | null {
	const before = Math.max(-1, ...runs.filter((run) => run < shown));
	if (before < 0) return null;
	const at = (run: number) => {
		const again = startedAgain(entries, graph, run);
		const last = (node: Node) => nodeRun(entries, node, run, again.has(node)).entries.at(-1);
		return { judge: last('judge'), fields: last('fields'), ocr: last('ocr') };
	};
	const then = at(before);
	const now = at(shown);
	const items: string[] = [];
	const decided = (entry: LogEntry | undefined) =>
		new Map(
			checksOf(entry)
				.filter((check) => check.outcome === 'ok' && check.value !== undefined)
				.map((check) => [String(check.field), check.value])
		);
	if (then.judge !== now.judge) {
		const old = decided(then.judge);
		const fresh = decided(now.judge);
		for (const field of COMPARED) {
			if (!old.has(field) || !fresh.has(field)) continue;
			const a = old.get(field) ?? null;
			const b = fresh.get(field) ?? null;
			if (JSON.stringify(a) === JSON.stringify(b)) continue;
			if (field === 'space' && (a === null || b === null)) continue;
			const label = fieldLabel(field, lookup);
			if (a === null)
				items.push(m.run_change_set({ field: label, after: describeValue(b, lookup) }));
			else if (b === null) items.push(m.run_change_unset({ field: label }));
			else {
				items.push(
					m.run_change({
						field: label,
						before: describeValue(a, lookup),
						after: describeValue(b, lookup)
					})
				);
			}
		}
	}
	if (then.fields !== now.fields) {
		const old = decided(then.fields);
		const fresh = decided(now.fields);
		const changed = [...fresh.keys()].filter(
			(field) =>
				field.startsWith('field:') &&
				old.has(field) &&
				JSON.stringify(old.get(field)) !== JSON.stringify(fresh.get(field))
		).length;
		if (changed === 1) items.push(m.run_change_fields_one());
		else if (changed > 1) items.push(m.run_change_fields({ count: String(changed) }));
	}
	const pdfa = (entry: LogEntry | undefined) => object(entry?.output).pdfa;
	if (then.ocr !== now.ocr && typeof pdfa(then.ocr) === 'boolean') {
		if (pdfa(then.ocr) === false && pdfa(now.ocr) === true) items.push(m.run_change_pdfa());
		if (pdfa(then.ocr) === true && pdfa(now.ocr) === false) items.push(m.run_change_not_pdfa());
	}
	return items.length > 0 ? { since: before, items } : null;
}
