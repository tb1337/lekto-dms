/**
 * The steps of the processing view: every node of a run with its state and what it did, the
 * nodes in four phases, how long a phase took, what keeps a run from going on, and how many
 * steps ended how.
 */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import type { Node, NodeState } from '#lib/pipeline.ts';
import { nodeRun, stateOf, type NodeRun } from '#lib/runs.ts';
import { confirmationOf, settled } from '#lib/step-summary.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];

export const PHASES = ['read', 'recognise', 'decide', 'file'] as const;
export type Phase = (typeof PHASES)[number];

const PHASE_OF: Record<Node, Phase> = {
	receive: 'read',
	ocr: 'read',
	pages: 'read',
	parse: 'read',
	signal_llm: 'recognise',
	signal_classifier: 'recognise',
	signal_neighbours: 'recognise',
	signal_facts: 'recognise',
	judge: 'decide',
	fields: 'decide',
	apply_rules: 'file',
	file: 'file'
};

export const PHASE_LABELS: Record<Phase, () => string> = {
	read: m.phase_read,
	recognise: m.phase_recognise,
	decide: m.phase_decide,
	file: m.phase_file
};

export function phaseOf(node: Node): Phase {
	return PHASE_OF[node];
}

/**
 * How a step that did not end OK by itself came to count as OK: a person confirmed it in the
 * inbox (`confirmed`, an entry of theirs in the run that names how it had ended), or a later
 * step of its run settled it (`settled`: the rules filed the document into the space the
 * verdict suggested; its entry stays uncertain).
 */
export type Overrule = 'confirmed' | 'settled';

export interface Step {
	node: Node;
	/** Its state in the run shown: live in the current run, by its last entry in a past one;
	 * null if it did not run there. */
	state: NodeState | null;
	/** What it did: its entries of the run shown, or those of the earlier run the run kept. */
	done: NodeRun;
	/** How it came to count as OK although it did not end so by itself; null if it did not. */
	overruled: Overrule | null;
}

/**
 * Every node of `nodes` in `run`: in the current run with its live state (a node waiting or
 * running there has nothing to keep), in a past one by its entries and how the run ended
 * (`status`, see `pastState`). `again`: the nodes the past run started again (`startedAgain`).
 */
export function stepsOf(
	nodes: readonly Node[],
	entries: readonly LogEntry[],
	states: ReadonlyMap<Node, NodeState>,
	run: { number: number; current: boolean; again: ReadonlySet<Node>; status: ProcessingStatus }
): Step[] {
	return nodes.map((node) => {
		if (run.current) {
			const state = states.get(node) ?? null;
			const done = nodeRun(entries, node, run.number, state?.status !== 'done');
			return { node, state, done, overruled: overruleOf(state, done.entries.at(-1)) };
		}
		const done = nodeRun(entries, node, run.number, run.again.has(node));
		const state = pastState(node, done.entries, run.status);
		return { node, state, done, overruled: overruleOf(state, done.entries.at(-1)) };
	});
}

/**
 * A node's state at the end of a past run that ended `status`: by its last entry (`stateOf`),
 * but OK for one left uncertain in a run that filed the document all the same: a later step of
 * the run settled it (`Overrule`).
 */
export function pastState(
	node: Node,
	entries: readonly LogEntry[],
	status: ProcessingStatus
): NodeState | null {
	const state = stateOf(node, entries);
	const last = entries.at(-1);
	if (!state || !last || status !== 'completed' || last.outcome !== 'uncertain') return state;
	const kept: NodeState = { ...state, outcome: 'ok' };
	return settled(kept, last) ? kept : state;
}

/** How a step in `state` with `last` as its last entry came to count as OK (`Overrule`). */
export function overruleOf(state: NodeState | null, last: LogEntry | undefined): Overrule | null {
	if (!last || state?.outcome !== 'ok') return null;
	if (confirmationOf(last)) return 'confirmed';
	return settled(state, last) ? 'settled' : null;
}

/** The steps in their phases, in graph order; a phase without a step is left out. */
export function phasesOf(steps: readonly Step[]): { phase: Phase; steps: Step[] }[] {
	return PHASES.map((phase) => ({
		phase,
		steps: steps.filter((step) => phaseOf(step.node) === phase)
	})).filter((group) => group.steps.length > 0);
}

/**
 * How long the steps of a phase took together in their run, from the first start to the last
 * end (`now` for one still running); steps the run kept from an earlier one do not count. Null
 * if none of them ran.
 */
export function phaseSeconds(steps: readonly Step[], now: Date): number | null {
	const own = steps.filter((step) => step.done.from === null && step.state?.started_at);
	if (own.length === 0) return null;
	const starts = own.map((step) => new Date(step.state?.started_at as string).getTime());
	const ends = own.map((step) =>
		step.state?.finished_at ? new Date(step.state.finished_at).getTime() : now.getTime()
	);
	return Math.max(0, (Math.max(...ends) - Math.min(...starts)) / 1000);
}

/** The steps that keep the run from going on by themselves: the failed ones, else the
 * uncertain ones. */
export function stuck(steps: readonly Step[]): Step[] {
	const failed = steps.filter((step) => step.state?.outcome === 'failed');
	return failed.length > 0 ? failed : steps.filter((step) => step.state?.outcome === 'uncertain');
}

/** How many steps of a run ended how, and how many it kept from an earlier run. */
export interface Counts {
	done: number;
	uncertain: number;
	failed: number;
	running: number;
	waiting: number;
	skipped: number;
	/** Steps the run did not start again: they keep what an earlier run did. */
	carried: number;
	/** The run they are from, if all are from one; else null. */
	carriedFrom: number | null;
}

/** The steps of a run by how they stand; a step that did not run there counts nowhere. */
export function countsOf(steps: readonly Step[]): Counts {
	const counts: Counts = {
		done: 0,
		uncertain: 0,
		failed: 0,
		running: 0,
		waiting: 0,
		skipped: 0,
		carried: 0,
		carriedFrom: null
	};
	const from = new Set<number>();
	for (const step of steps) {
		const state = step.state;
		if (state === null) continue;
		if (step.done.from !== null) {
			counts.carried += 1;
			from.add(step.done.from);
		} else if (state.status === 'running') counts.running += 1;
		else if (state.status === 'waiting') counts.waiting += 1;
		else if (state.status === 'skipped') counts.skipped += 1;
		else if (state.outcome === 'failed') counts.failed += 1;
		else if (state.outcome === 'uncertain') counts.uncertain += 1;
		else counts.done += 1;
	}
	counts.carriedFrom = from.size === 1 ? [...from][0] : null;
	return counts;
}
