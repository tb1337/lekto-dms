/** The names of the nodes of the processing graph, as people read them ("step"). */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

type Node = components['schemas']['Node'];

export const NODE_LABELS: Record<Node, () => string> = {
	receive: m.node_receive,
	ocr: m.node_ocr,
	pages: m.node_pages,
	parse: m.node_parse,
	classify: m.node_classify,
	extract_fields: m.node_extract_fields,
	apply_rules: m.node_apply_rules,
	file: m.node_file
};
