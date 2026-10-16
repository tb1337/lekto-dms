/**
 * The runs of a document in its processing log: which there are, what a node did in one of
 * them, and how a past run ended. A run that starts at a node runs it and every node after it
 * again; the nodes before keep what they did in an earlier run, and a run works with that.
 */
import type { components } from '#lib/api/schema.ts';
import { descendants, type GraphNode, type Node, type NodeState } from '#lib/pipeline.ts';
import { usageOf } from '#lib/usage.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];

/** The runs in the log and the current one, the latest first. */
export function runNumbers(entries: readonly LogEntry[], current: number): number[] {
	return [...new Set([current, ...entries.map((entry) => entry.run)])].sort((a, b) => b - a);
}

/**
 * The nodes a past run started again: those that ran in it, and every node after one of them
 * (they were reset, whether or not they got to run).
 */
export function startedAgain(
	entries: readonly LogEntry[],
	graph: readonly GraphNode[],
	run: number
): Set<Node> {
	const again = new Set<Node>();
	for (const node of new Set(entries.filter((entry) => entry.run === run).map((e) => e.node))) {
		again.add(node);
		for (const after of descendants(graph, node)) again.add(after);
	}
	return again;
}

export interface NodeRun {
	/** The node's entries, in the order they were written. */
	entries: LogEntry[];
	/** The earlier run they are from, for a node the run did not start again; else null. */
	from: number | null;
}

/**
 * What `node` did in `run`: its entries of that run, or, if the run did not start it again
 * (`again` false), those of the latest earlier run that ran it.
 */
export function nodeRun(
	entries: readonly LogEntry[],
	node: Node,
	run: number,
	again: boolean
): NodeRun {
	const own = entries.filter((entry) => entry.node === node && entry.run === run);
	if (own.length > 0 || again) return { entries: own, from: null };
	const before = entries.filter((entry) => entry.node === node && entry.run < run);
	if (before.length === 0) return { entries: [], from: null };
	const from = Math.max(...before.map((entry) => entry.run));
	return { entries: before.filter((entry) => entry.run === from), from };
}

/** A node's state at the end of a past run, by its last entry; null if it did not run. */
export function stateOf(node: Node, entries: readonly LogEntry[]): NodeState | null {
	const last = entries.at(-1);
	if (!last) return null;
	const finished = new Date(new Date(last.started_at).getTime() + last.duration_ms);
	return {
		node,
		status: 'done',
		outcome: last.outcome,
		started_at: last.started_at,
		finished_at: finished.toISOString()
	};
}

/**
 * How a past run ended: done once it filed the document (also after a confirmation), else
 * failed or for review by the results it worked with, its own and those it kept.
 */
export function pastStatus(
	entries: readonly LogEntry[],
	graph: readonly GraphNode[],
	run: number
): ProcessingStatus {
	const again = startedAgain(entries, graph, run);
	const nodes = [...new Set(entries.map((entry) => entry.node))];
	const last = nodes.map((node) => nodeRun(entries, node, run, again.has(node)).entries.at(-1));
	if (last.some((entry) => entry?.node === 'file' && entry.run === run && entry.outcome === 'ok'))
		return 'completed';
	if (last.some((entry) => entry?.outcome === 'failed')) return 'failed';
	if (last.some((entry) => entry?.outcome === 'uncertain')) return 'review';
	return 'completed';
}

export interface RunSpan {
	started: string;
	/** When its last entry ended. */
	finished: string;
}

/** When a run began and when its last entry ended, by its entries; null without any. */
export function runSpan(entries: readonly LogEntry[], run: number): RunSpan | null {
	const own = entries.filter((entry) => entry.run === run);
	if (own.length === 0) return null;
	const starts = own.map((entry) => new Date(entry.started_at).getTime());
	const ends = own.map((entry) => new Date(entry.started_at).getTime() + entry.duration_ms);
	return {
		started: new Date(Math.min(...starts)).toISOString(),
		finished: new Date(Math.max(...ends)).toISOString()
	};
}

/** The language model's tokens in a run; null if no entry reports any. */
export function runTokens(
	entries: readonly LogEntry[],
	run: number
): { input: number; output: number } | null {
	let input = 0;
	let output = 0;
	let any = false;
	for (const entry of entries) {
		if (entry.run !== run) continue;
		const usage = usageOf(entry.output);
		if (!usage) continue;
		any = true;
		input += usage.input ?? 0;
		output += usage.output ?? 0;
	}
	return any ? { input, output } : null;
}
