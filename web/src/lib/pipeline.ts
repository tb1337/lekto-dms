/**
 * The processing graph (`GET /pipeline`) and what it says about a document's nodes
 * (`processing.nodes`): which nodes a reprocessing may start from, and what comes after a node.
 */
import type { components } from '#lib/api/schema.ts';

export type Node = components['schemas']['Node'];
export type GraphNode = components['schemas']['GraphNodeOut'];
export type NodeState = components['schemas']['NodeStateOut'];
export type Processing = components['schemas']['Processing'];

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
