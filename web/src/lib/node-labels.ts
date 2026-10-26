/** The names of the nodes of the processing graph, as people read them ("step"). */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

type Node = components['schemas']['Node'];

export const NODE_LABELS: Record<Node, () => string> = {
	receive: m.node_receive,
	ocr: m.node_ocr,
	pages: m.node_pages,
	parse: m.node_parse,
	signal_llm: m.node_signal_llm,
	signal_classifier: m.node_signal_classifier,
	signal_neighbours: m.node_signal_neighbours,
	signal_facts: m.node_signal_facts,
	judge: m.node_judge,
	fields: m.node_fields,
	relate: m.node_relate,
	apply_rules: m.node_apply_rules,
	file: m.node_file
};
