/**
 * Applying a rule to existing documents: what the preview selects and what the request holds
 * (decision E3: documents with a conflict are only applied with their own consent, which
 * becomes `accept_conflicts`), and how often the progress is asked for.
 */
import type { components } from '#lib/api/schema.ts';
import { describeValue, fieldLabel } from '#lib/describe.ts';
import { spaceNameFor, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { labelled, outputReasonText, reasonsText } from '#lib/reasons.ts';

export type PreviewItem = components['schemas']['ApplyPreviewItemOut'];
export type Application = components['schemas']['RuleApplicationOut'];
export type ApplyRequest = components['schemas']['ApplyRequest'];

export function hasConflict(item: PreviewItem): boolean {
	return item.conflicts.length > 0;
}

/** The documents chosen when they show up: those without a conflict. */
export function preselected(items: readonly PreviewItem[]): string[] {
	return items.filter((item) => !hasConflict(item)).map((item) => item.document_id);
}

/** The request for the chosen documents, in the order of the preview. A conflict counts only
 * as accepted; a chosen document with a conflict that is not accepted stays out. */
export function applyRequest(
	version: number,
	items: readonly PreviewItem[],
	chosen: ReadonlySet<string>,
	accepted: ReadonlySet<string>
): ApplyRequest {
	const included = items.filter((item) =>
		hasConflict(item) ? accepted.has(item.document_id) : chosen.has(item.document_id)
	);
	return {
		version,
		document_ids: included.map((item) => item.document_id),
		accept_conflicts: included.filter(hasConflict).map((item) => item.document_id)
	};
}

export function isFinished(application: Pick<Application, 'status'>): boolean {
	return application.status === 'done' || application.status === 'failed';
}

/** Every second at first, then every three. */
export function pollDelay(elapsedMs: number): number {
	return elapsedMs < 10_000 ? 1000 : 3000;
}

/**
 * Ask for the progress until the application is finished or `signal` aborts; `update` gets each
 * answer. Resolves with the last one.
 */
export async function follow(
	first: Application,
	load: (id: string) => Promise<Application>,
	update: (application: Application) => void,
	signal: AbortSignal,
	wait: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
): Promise<Application> {
	let current = first;
	let elapsed = 0;
	while (!isFinished(current) && !signal.aborted) {
		const delay = pollDelay(elapsed);
		await wait(delay);
		elapsed += delay;
		if (signal.aborted) break;
		current = await load(current.id);
		update(current);
	}
	return current;
}

export type Outcome = components['schemas']['ApplyOutcomeOut'];

/** The notes of a chain step that tell why it stopped or what did not act. */
const CHAIN_NOTES = new Set(['refused', 'conflict']);

/**
 * Where applying the rule takes a document, step by step: into the space `rule` files it into,
 * then what the rules of each space it enters do ("then tags Haushaltskosten (rule “Rechnungen”
 * of Haushalt)"), where the chain stops and why, and where it ends up.
 */
export function chainLines(
	outcome: Outcome,
	rule: string,
	lookup: Lookup | null,
	me: string | undefined
): string[] {
	const name = (id: string) => spaceNameFor(id, lookup, me);
	const first = outcome.chain[0]?.space_id ?? outcome.space_id;
	const lines = [m.rule_chain_into({ space: name(first), rule })];
	const visited = [first];
	for (const step of outcome.chain) {
		const here = name(step.space_id);
		for (const report of step.rules) {
			for (const effect of report.applied) {
				if (effect.field === 'space') continue; // the move, below
				const change = `${fieldLabel(effect.field, lookup)} ${describeValue(effect.new, lookup)}`;
				lines.push(m.rule_chain_then({ change, rule: report.name, space: here }));
			}
			for (const note of report.notes.filter((entry) => CHAIN_NOTES.has(entry.kind))) {
				const field = fieldLabel(note.field, lookup);
				const reason =
					reasonsText(note.reasons, note.reason, {
						field: (name) => fieldLabel(name, lookup)
					}) ?? note.reason;
				lines.push(m.rule_chain_note({ field, reason, rule: report.name, space: here }));
			}
		}
		if (step.moved_to !== null) {
			const mover = step.rules.find((report) =>
				report.applied.some((effect) => effect.field === 'space')
			);
			lines.push(
				m.rule_chain_moved({ space: name(step.moved_to), rule: mover?.name ?? '', from: here })
			);
			visited.push(step.moved_to);
		}
		if (step.looped_to !== null) {
			const spaces = [...visited, step.looped_to].map(name).join(' → ');
			lines.push(m.rule_chain_loop({ spaces }));
		} else if (step.problem !== null) {
			const problem =
				outputReasonText(step.problem_reason, step.problem, labelled(lookup)) ?? step.problem;
			lines.push(m.rule_chain_problem({ problem }));
		}
	}
	if (outcome.chain.length > 0) lines.push(m.rule_chain_end({ space: name(outcome.space_id) }));
	return lines;
}
