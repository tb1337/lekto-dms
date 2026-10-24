/**
 * The processing graph (`GET /pipeline`, asked once) and what it says about a document's nodes
 * (`processing.nodes`): which nodes a reprocessing may start from, and what comes after a node.
 */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';

export type Pipeline = components['schemas']['PipelineOut'];
export type Node = components['schemas']['Node'];
export type GraphNode = components['schemas']['GraphNodeOut'];
export type NodeState = components['schemas']['NodeStateOut'];
export type Processing = components['schemas']['Processing'];

let asked: Promise<Pipeline> | null = null;

/** The graph and what the installation has (vision, logos, the search by meaning), asked of
 * the API once for the session; a request that failed is asked again next time. */
export function pipeline(): Promise<Pipeline> {
	asked ??= unwrap(api.GET('/api/v1/pipeline')).catch((error: unknown) => {
		asked = null;
		throw error;
	});
	return asked;
}

/** For tests: ask again. */
export function forgetPipeline(): void {
	asked = null;
}

/** The nodes that depend on `node`, directly or through others. */
export function descendants(graph: readonly GraphNode[], node: Node): Set<Node> {
	const found = new Set<Node>();
	const pending: Node[] = [node];
	while (pending.length > 0) {
		const current = pending.pop() as Node;
		for (const entry of graph) {
			if (entry.requires.includes(current) && !found.has(entry.node)) {
				found.add(entry.node);
				pending.push(entry.node);
			}
		}
	}
	return found;
}

/**
 * The nodes a reprocessing may start from, in graph order: not receiving, never past a failed
 * node (the node itself or one after it must be the failed one), and not filing while uncertain
 * results wait for confirmation. Mirrors the rules of the backend.
 */
export function reprocessable(graph: readonly GraphNode[], processing: Processing): Node[] {
	const failed = processing.nodes.filter((state) => state.outcome === 'failed');
	return graph
		.map((entry) => entry.node)
		.filter((node) => {
			if (node === 'receive') return false;
			if (node === 'file' && processing.status === 'review') return false;
			const again = descendants(graph, node);
			return failed.every((state) => state.node === node || again.has(state.node));
		});
}

/**
 * The nodes in rows by level: a node's level is one more than the highest level of the nodes it
 * needs, so nodes that run side by side share a row.
 */
export function levels(graph: readonly GraphNode[]): Node[][] {
	const level = new Map<Node, number>();
	for (const entry of graph) {
		const needed = entry.requires.map((node) => level.get(node) ?? 0);
		level.set(entry.node, needed.length === 0 ? 0 : Math.max(...needed) + 1);
	}
	const rows: Node[][] = [];
	for (const entry of graph) {
		const row = level.get(entry.node) ?? 0;
		(rows[row] ??= []).push(entry.node);
	}
	return rows;
}

export interface Progress {
	/** Nodes done or skipped. */
	done: number;
	/** Nodes of the run. */
	total: number;
	/** Nodes a worker is at right now. */
	running: Node[];
}

/** How far the processing of a document has come. */
export function progress(processing: Processing): Progress {
	const nodes = processing.nodes;
	return {
		done: nodes.filter((state) => state.status === 'done' || state.status === 'skipped').length,
		total: nodes.length,
		running: nodes.filter((state) => state.status === 'running').map((state) => state.node)
	};
}

/** Seconds a node took, or has been running for at `now`; null while it has not started. */
export function durationSeconds(state: NodeState, now: Date): number | null {
	if (state.started_at === null) return null;
	const end = state.finished_at === null ? now : new Date(state.finished_at);
	return Math.max(0, (end.getTime() - new Date(state.started_at).getTime()) / 1000);
}

/**
 * Whether the document may have its text, so its facts can be asked for (409 before): once
 * `parse` read it in the first run. A later run keeps the text of the runs before.
 */
export function hasText(processing: Processing): boolean {
	if (processing.run > 1) return true;
	return processing.nodes.some(
		(state) => state.node === 'parse' && state.status === 'done' && state.outcome !== 'failed'
	);
}
