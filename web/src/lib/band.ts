/**
 * The band of a run in the processing view (Tobi chose it, 23.10.2026): the whole run in one
 * bar, its width the time, its colour how each step ended. The four phases share the bar by
 * how long they took (each keeps a width of its own); inside a phase the steps that ran one
 * after another follow each other by their duration, and the steps that ran side by side lie
 * on top of each other: the longest as the bar, the others as thin stripes below it.
 *
 * Every step is drawn. Steps the run kept from an earlier run took no time in it: they stand
 * muted, a phase of only such steps keeps a small part of the bar, one beside steps of the run
 * a few pixels. When the run itself took next to no time (it only filed after a confirmation),
 * or its times are not known, the band tells how the steps stand: every step alike.
 */
import { durationSeconds, type GraphNode, type Node } from '#lib/pipeline.ts';
import { PHASES, phaseOf, type Overrule, type Phase, type Step } from '#lib/steps.ts';

/** How a step looks in the band: how it ended, or `carried` for one an earlier run did. */
export type BandTone = 'green' | 'yellow' | 'red' | 'running' | 'waiting' | 'carried';

export interface BandStep {
	node: Node;
	tone: BandTone;
	/** How long it took or has been running in the run; null while it waits, for a step the
	 * run kept, and when the band tells no times. */
	seconds: number | null;
	/** Its length beside the first step of its group (1 for that one). */
	share: number;
	/** The earlier run a step the run kept is from; null for the run's own. */
	from: number | null;
	/** How it came to count as OK although it did not end so by itself. */
	overruled: Overrule | null;
}

/** Steps that ran side by side: the first as the bar, the others below it. */
export interface BandGroup {
	steps: BandStep[];
	/** How it grows beside the other groups of its phase (`flex-grow`). */
	grow: number;
	/** The width it keeps at least, in pixels (`flex-basis`). */
	basis: number;
}

export interface BandPhase {
	phase: Phase;
	/** What it weighs for its part of the bar beside the other phases: its own time, or its
	 * number of groups when the band tells no times; null for a phase the run kept whole,
	 * which keeps a small part of its own (`CARRIED_PHASE`). */
	weight: number | null;
	groups: BandGroup[];
	/** Every step of it is one the run kept from an earlier run. */
	carried: boolean;
	/** The run all its kept steps are from, if they are from one; else null. */
	from: number | null;
}

/** The smallest part of the bar a phase keeps while the width of the bar is not known. */
export const MIN_PHASE = 0.1;
/** The smallest part of the bar a phase with steps of the run keeps beside its label. */
export const MIN_OWN_PHASE = 0.06;
/** The part of the bar a phase the run kept whole keeps, unless its label needs more. */
export const CARRIED_PHASE = 0.08;
/** The time of its own steps from which the band tells the run's times, in seconds. */
export const TIMED_FROM = 1;
/** The length a waiting step stands for, in seconds of the run. */
const WAITING_SECONDS = 1;
/** The shortest stripe below the bar of a group. */
const MIN_SHARE = 0.03;
/** The stripe of a kept step below a step of the run. */
const CARRIED_SHARE = 0.2;
/** The width a step of the run keeps at least, in pixels: a step of 0 seconds stays a sliver. */
export const STEP_BASIS = 4;
/** The width a kept step keeps beside steps of the run, in pixels. */
export const CARRIED_BASIS = 10;
/** The gap between the phases and between the groups of a phase, in pixels. */
export const PHASE_GAP = 4;
export const GROUP_GAP = 2;

function toneOf(step: Step): BandTone | null {
	const state = step.state;
	if (state === null || state.status === 'skipped') return null;
	if (step.done.from !== null) return 'carried';
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

/** The steps by their level. */
function byLevel(steps: readonly Step[], level: ReadonlyMap<Node, number>): Map<number, Step[]> {
	const found = new Map<number, Step[]>();
	for (const step of steps) {
		const at = level.get(step.node) ?? 0;
		found.set(at, [...(found.get(at) ?? []), step]);
	}
	return found;
}

/** How long a step of the run took or has been running; null while it waits. */
function secondsOf(step: Step, now: Date): number | null {
	if (step.done.from !== null || !step.state || step.state.status === 'waiting') return null;
	return durationSeconds(step.state, now);
}

/**
 * The band of a run's steps: its phases with their steps in groups. Skipped steps and steps
 * that did not run are left out, a phase without any step too. `timed` false: which steps the
 * run kept is not known (no log yet, or a reader's view of a later run), so their times would
 * mix in an earlier run's: the band tells only how the steps stand.
 */
export function bandOf(
	steps: readonly Step[],
	graph: readonly GraphNode[],
	now: Date,
	timed = true
): BandPhase[] {
	const level = levelsOf(graph);
	const drawn = steps.filter((step) => toneOf(step) !== null);
	const own = drawn.filter((step) => step.done.from === null);
	// The run's own time, the steps side by side counting once: its longest.
	const runSeconds = [...byLevel(own, level).values()].reduce(
		(sum, members) => sum + Math.max(...members.map((step) => secondsOf(step, now) ?? 0)),
		0
	);
	const timesTold = timed && runSeconds >= TIMED_FROM;
	return PHASES.flatMap((phase) => {
		const members = drawn.filter((step) => phaseOf(step.node) === phase);
		if (members.length === 0) return [];
		const built = [...byLevel(members, level).entries()]
			.sort(([a], [b]) => a - b)
			.map(([, group]) => groupOf(group, now, timesTold));
		const carried = members.every((step) => step.done.from !== null);
		const kept = new Set(
			members.flatMap((step) => (step.done.from === null ? [] : [step.done.from]))
		);
		const seconds = built.reduce((sum, entry) => sum + entry.seconds, 0);
		const ownSeconds = built
			.filter((entry) => !entry.kept)
			.reduce((sum, entry) => sum + entry.seconds, 0);
		const groups = built.map((entry) => {
			if (!timesTold || carried) return { steps: entry.steps, grow: 1, basis: 0 };
			if (entry.kept) return { steps: entry.steps, grow: 0, basis: CARRIED_BASIS };
			return {
				steps: entry.steps,
				grow: ownSeconds > 0 ? entry.seconds / ownSeconds : 1,
				basis: STEP_BASIS
			};
		});
		return [
			{
				phase,
				weight: timesTold ? (carried ? null : seconds) : groups.length,
				groups,
				carried,
				from: kept.size === 1 ? [...kept][0] : null
			}
		];
	});
}

/** A group of steps side by side: the run's longest first, then its others, then the kept ones;
 * `seconds` its length in the run, `kept` whether it holds only kept steps. */
function groupOf(
	members: readonly Step[],
	now: Date,
	timesTold: boolean
): { steps: BandStep[]; seconds: number; kept: boolean } {
	const length = (step: Step) =>
		step.state?.status === 'waiting' ? WAITING_SECONDS : (secondsOf(step, now) ?? 0);
	const own = members
		.filter((step) => step.done.from === null)
		.sort((a, b) => (timesTold ? length(b) - length(a) : 0));
	const kept = members.filter((step) => step.done.from !== null);
	const longest = own.length > 0 ? length(own[0]) : 0;
	const steps = [...own, ...kept].map((step, index) => {
		const tone = toneOf(step) as BandTone;
		const seconds = timesTold ? secondsOf(step, now) : null;
		let share = 1;
		if (index > 0 && step.done.from !== null) share = CARRIED_SHARE;
		else if (index > 0 && timesTold)
			share = Math.min(1, Math.max(MIN_SHARE, length(step) / Math.max(longest, Number.EPSILON)));
		return {
			node: step.node,
			tone,
			seconds,
			share,
			from: step.done.from,
			overruled: step.overruled
		};
	});
	return { steps, seconds: own.length > 0 ? longest : 0, kept: own.length === 0 };
}

/**
 * The parts of the bar, 0 to 1, for phases weighing `weights`: by weight, but each at least
 * its `minimum`; a phase weighing null keeps exactly its minimum. Without any weight, the
 * phases share what is left equally; minimums adding up to more than the bar shrink alike.
 */
export function widthsOf(
	weights: readonly (number | null)[],
	minimum: readonly number[] = weights.map(() => MIN_PHASE)
): number[] {
	const count = weights.length;
	if (count === 0) return [];
	const floor = weights.map((_, index) => Math.max(0, minimum[index] ?? 0));
	const floors = floor.reduce((sum, value) => sum + value, 0);
	if (floors >= 1) return floor.map((value) => (floors > 0 ? value / floors : 1 / count));
	const held = new Set(weights.flatMap((weight, index) => (weight === null ? [index] : [])));
	// Holding one phase at its minimum takes room from the others, which may push another
	// below its own: repeat until none is.
	for (;;) {
		const free = weights.flatMap((_, index) => (held.has(index) ? [] : [index]));
		const rest = 1 - [...held].reduce((sum, index) => sum + floor[index], 0);
		if (free.length === 0) return floor.map((value) => value / (1 - rest));
		const left = free.reduce((sum, index) => sum + (weights[index] ?? 0), 0);
		const width = (index: number) =>
			left > 0 ? ((weights[index] ?? 0) / left) * rest : rest / free.length;
		const below = free.find((index) => width(index) < floor[index]);
		if (below === undefined)
			return weights.map((_, index) => (held.has(index) ? floor[index] : width(index)));
		held.add(below);
	}
}

/** The minimum part of the bar of each phase, the bar `width` pixels wide: room for its label
 * (`labels`, in pixels) and a share of its own; `MIN_PHASE` while the width is not known. */
export function minimumsOf(
	phases: readonly BandPhase[],
	width: number,
	labels: readonly number[]
): number[] {
	return phases.map((phase, index) => {
		if (width <= 0) return MIN_PHASE;
		const own = phase.weight === null ? CARRIED_PHASE : MIN_OWN_PHASE;
		return Math.max(own, (labels[index] ?? 0) / width);
	});
}

/** The widths of a phase's groups in pixels, the phase `width` pixels wide. */
export function groupWidths(width: number, groups: readonly BandGroup[]): number[] {
	const gaps = GROUP_GAP * Math.max(0, groups.length - 1);
	const room = Math.max(0, width - gaps - groups.reduce((sum, group) => sum + group.basis, 0));
	const grows = groups.reduce((sum, group) => sum + group.grow, 0);
	// The flexbox rule: growing factors adding up to less than 1 fill only that part.
	const filled = room * Math.min(1, grows);
	return groups.map((group) => group.basis + (grows > 0 ? (filled * group.grow) / grows : 0));
}

/** The width a text needs at `size` pixels, estimated (Geist, semibold): wider in capitals with
 * the phase labels' letter spacing. */
export function textWidth(text: string, size: number, capitals = false): number {
	return Math.ceil(text.length * size * (capitals ? 0.8 : 0.62));
}

/** The label that fits a segment `width` pixels wide: the step with its time, the step alone,
 * or none; never cut. */
export function labelFor(
	name: string,
	time: string | null,
	width: number,
	size = 11
): string | null {
	const padding = 16;
	const full = time === null ? name : `${name} ${time}`;
	if (textWidth(full, size) + padding <= width) return full;
	if (time !== null && textWidth(name, size) + padding <= width) return name;
	return null;
}
