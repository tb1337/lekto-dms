/**
 * The band of a run in the processing view (Tobi chose it, 23.10.2026): the whole run in one
 * bar, its width the time, its colour how each step ended. The four phases share the bar by
 * how long they took (a short one keeps a width of its own); inside a phase the steps that ran
 * one after another follow each other by their duration, and the steps that ran side by side
 * lie on top of each other: the longest as the bar, the others as thin stripes below it.
 */
import { durationSeconds, type GraphNode, type Node } from '#lib/pipeline.ts';
import { PHASES, phaseOf, type Phase, type Step } from '#lib/steps.ts';

/** How a step looks in the band. */
export type BandTone = 'green' | 'yellow' | 'red' | 'running' | 'waiting';

export interface BandStep {
	node: Node;
	tone: BandTone;
	/** How long it took or has been running; null while it waits. */
	seconds: number | null;
	/** Its length beside the longest step of its group (1 for that one). */
	share: number;
}

/** Steps that ran side by side: the longest first, the others below it. */
export interface BandGroup {
	steps: BandStep[];
	/** Its length within the phase. */
	weight: number;
}

export interface BandPhase {
	phase: Phase;
	/** Its part of the bar, 0 to 1; the parts add up to 1. */
	width: number;
	groups: BandGroup[];
	/** Every step of it is one the run kept from an earlier run. */
	carried: boolean;
}

/** The smallest part of the bar a phase keeps, so a short phase stays visible. */
export const MIN_PHASE = 0.1;
/** The length a waiting step stands for, in seconds of the run, at least. */
const WAITING_SECONDS = 1;
/** The shortest stripe below the longest step of a group. */
const MIN_SHARE = 0.03;

function toneOf(step: Step): BandTone | null {
	const state = step.state;
	if (state === null || state.status === 'skipped') return null;
	if (state.status === 'running') return 'running';
	if (state.status === 'waiting') return 'waiting';
	if (state.outcome === 'failed') return 'red';
	if (state.outcome === 'uncertain') return 'yellow';
	return 'green';
}

/** The level of each node: one more than the highest level of the nodes it needs. */
function levelsOf(graph: readonly GraphNode[]): Map<Node, number> {
	const level = new Map<Node, number>();
	for (const entry of graph) {
		const needed = entry.requires.map((node) => level.get(node) ?? 0);
		level.set(entry.node, needed.length === 0 ? 0 : Math.max(...needed) + 1);
	}
	return level;
}

/**
 * The band of a run's steps: its phases with their part of the bar and their steps in groups.
 * Steps the run kept from an earlier one take no time in it; a phase of only such steps keeps
 * the smallest part and says so (`carried`). Skipped steps and steps that did not run are left
 * out; a phase without any step at all too. `timed` false: which steps the run kept is not
 * known (no log yet, or a reader's view of a later run), so their times would mix in an earlier
 * run's: the band tells only how the steps stand, steps one after another in equal parts.
 */
export function bandOf(
	steps: readonly Step[],
	graph: readonly GraphNode[],
	now: Date,
	timed = true
): BandPhase[] {
	const level = levelsOf(graph);
	const phases = PHASES.map((phase) => {
		const own = steps.filter(
			(step) => phaseOf(step.node) === phase && step.done.from === null && toneOf(step) !== null
		);
		const carried = steps.some(
			(step) => phaseOf(step.node) === phase && step.done.from !== null && step.state !== null
		);
		const byLevel = new Map<number, Step[]>();
		for (const step of own) {
			const at = level.get(step.node) ?? 0;
			byLevel.set(at, [...(byLevel.get(at) ?? []), step]);
		}
		const groups = [...byLevel.entries()]
			.sort(([a], [b]) => a - b)
			.map(([, members]) => group(members, now, timed));
		const seconds = groups.reduce((sum, entry) => sum + entry.weight, 0);
		return { phase, groups, seconds, carried: own.length === 0 && carried };
	}).filter((entry) => entry.groups.length > 0 || entry.carried);
	const widths = shares(phases.map((entry) => entry.seconds));
	return phases.map((entry, index) => ({
		phase: entry.phase,
		width: widths[index],
		groups: entry.groups,
		carried: entry.carried
	}));
}

function group(members: readonly Step[], now: Date, timed: boolean): BandGroup {
	const steps = members.map((step) => {
		const tone = toneOf(step) as BandTone;
		const seconds = timed && step.state ? durationSeconds(step.state, now) : null;
		return { node: step.node, tone, seconds: tone === 'waiting' ? null : seconds };
	});
	const length = (step: { seconds: number | null }) => step.seconds ?? WAITING_SECONDS;
	const sorted = [...steps].sort((a, b) => length(b) - length(a));
	const longest = Math.max(length(sorted[0]), Number.EPSILON);
	return {
		weight: Math.max(length(sorted[0]), WAITING_SECONDS / 10),
		steps: sorted.map((step) => ({
			...step,
			share: Math.min(1, Math.max(MIN_SHARE, length(step) / longest))
		}))
	};
}

/**
 * The parts of the bar for phases that took `seconds`: by time, but at least `MIN_PHASE` each;
 * the others share what is left by their time. Without any time, equal parts.
 */
export function shares(seconds: readonly number[]): number[] {
	const count = seconds.length;
	if (count === 0) return [];
	const total = seconds.reduce((sum, value) => sum + value, 0);
	if (total <= 0 || count * MIN_PHASE >= 1) return seconds.map(() => 1 / count);
	const small = new Set<number>();
	// Fixing one phase at its minimum takes room from the others, which may push another
	// below it: repeat until none is.
	for (;;) {
		const rest = 1 - small.size * MIN_PHASE;
		const left = seconds.reduce((sum, value, index) => (small.has(index) ? sum : sum + value), 0);
		const below = seconds.findIndex(
			(value, index) => !small.has(index) && (left <= 0 || (value / left) * rest < MIN_PHASE)
		);
		if (below === -1) {
			return seconds.map((value, index) =>
				small.has(index) ? MIN_PHASE : left > 0 ? (value / left) * rest : rest
			);
		}
		small.add(below);
		if (small.size === count) return seconds.map(() => 1 / count);
	}
}
