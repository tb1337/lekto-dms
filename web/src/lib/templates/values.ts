import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { IDENTIFIER_KINDS, NUMBER_KINDS, kindLabel } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';

/** The values a template sees, as the server names them (`field.<key>` aside). */
export const TEMPLATE_NAMES = [
	'title',
	'contact',
	'document_type',
	'topic',
	'document_date',
	'added',
	'tags',
	'contact_groups',
	'document_type_groups',
	'space',
	'uploaded_by',
	'filename',
	'original_filename',
	'channel',
	'pages'
] as const;
export type TemplateName = (typeof TEMPLATE_NAMES)[number];

export const TEMPLATE_NAME_LABELS: Record<TemplateName, () => string> = {
	title: m.field_title,
	contact: m.field_contact,
	document_type: m.field_document_type,
	topic: m.field_topic,
	document_date: m.field_date,
	added: m.template_value_added,
	tags: m.field_tags,
	contact_groups: m.template_value_contact_groups,
	document_type_groups: m.template_value_document_type_groups,
	space: m.field_space,
	uploaded_by: m.template_value_uploaded_by,
	filename: m.template_value_filename,
	original_filename: m.template_value_original_filename,
	channel: m.template_value_channel,
	pages: m.template_value_pages
};

/** Who a template is for: a rule or title pattern, or a webhook's body (JSON, more values). */
export type TemplatePurpose = 'rule' | 'webhook';

/** What a webhook's template sees besides a rule's values, as the server names them. */
export const WEBHOOK_TEMPLATE_NAMES = [
	'event.type',
	'event.id',
	'event.occurred_at',
	'document_id',
	'lane',
	'link',
	'rule.name',
	'rule.id',
	'task.id',
	'task.callback',
	'task.token',
	'task.deadline'
] as const;
export type WebhookTemplateName = (typeof WEBHOOK_TEMPLATE_NAMES)[number];

export const WEBHOOK_TEMPLATE_NAME_LABELS: Record<WebhookTemplateName, () => string> = {
	'event.type': m.template_value_event_type,
	'event.id': m.template_value_event_id,
	'event.occurred_at': m.template_value_event_occurred_at,
	document_id: m.template_value_document_id,
	lane: m.template_value_lane,
	link: m.template_value_link,
	'rule.name': m.template_value_rule_name,
	'rule.id': m.template_value_rule_id,
	'task.id': m.template_value_task_id,
	'task.callback': m.template_value_task_callback,
	'task.token': m.template_value_task_token,
	'task.deadline': m.template_value_task_deadline
};

/** What a rule's template sees of the steps before it that ask: `steps.<name>`, the answer. */
export function stepNames(steps: readonly string[]): { name: string; label: string }[] {
	return steps.map((step) => ({
		name: `steps.${step}`,
		label: m.template_value_step({ name: step })
	}));
}

/** The parts of a GiroCode a template sees (`facts.girocode.<part>`). */
const GIROCODE_PARTS = ['amount', 'iban', 'name', 'purpose', 'bic'] as const;

/** What a template sees of the document's facts (#145): its own value of each kind
 * (`facts.<kind>`), the one of another document it refers to (`facts.refers.<kind>`, for the
 * kinds a document refers by), the GiroCode on its pages, and all facts (`fact_list`). A
 * person's kinds alone are not among them. */
export function factNames(): { name: string; label: string }[] {
	const kinds = [...new Set([...NUMBER_KINDS, ...IDENTIFIER_KINDS])];
	return [
		...kinds.map((kind) => ({
			name: `facts.${kind}`,
			label: m.template_value_fact({ kind: kindLabel(kind) })
		})),
		...NUMBER_KINDS.map((kind) => ({
			name: `facts.refers.${kind}`,
			label: m.template_value_fact_refers({ kind: kindLabel(kind) })
		})),
		...GIROCODE_PARTS.map((part) => ({
			name: `facts.girocode.${part}`,
			label: m.template_value_girocode({ part: GIROCODE_LABELS[part]() })
		})),
		{ name: 'fact_list', label: m.template_value_fact_list() }
	];
}

const GIROCODE_LABELS: Record<(typeof GIROCODE_PARTS)[number], () => string> = {
	amount: m.code_giro_amount,
	iban: m.identifier_kind_iban,
	name: m.code_giro_name,
	purpose: m.code_giro_purpose,
	bic: m.code_giro_bic
};

/** The values a template of `purpose` sees, with their names, for completion and lists; in a
 * rule's step also what the steps before it that ask brought (`steps`). */
export function templateNames(
	purpose: TemplatePurpose,
	steps: readonly string[] = []
): { name: string; label: string }[] {
	const names = [
		...TEMPLATE_NAMES.map((name) => ({ name, label: TEMPLATE_NAME_LABELS[name]() })),
		...factNames(),
		...stepNames(steps)
	];
	if (purpose === 'rule') return names;
	return [
		...names,
		...WEBHOOK_TEMPLATE_NAMES.map((name) => ({
			name,
			label: WEBHOOK_TEMPLATE_NAME_LABELS[name]()
		}))
	];
}

/** The lists among the values: a template joins them (`{{ tags | join: ', ' }}`). */
export const LIST_NAMES: ReadonlySet<string> = new Set([
	'tags',
	'contact_groups',
	'document_type_groups',
	'fact_list'
]);

/** The fields a template may use: those of `documentType` (undefined: every field, as in a
 * rule; null: a type not saved yet, so the fields for every type). */
export function usableFields(
	fields: readonly FieldDefinition[],
	documentType: string | null | undefined
): FieldDefinition[] {
	return fields.filter(
		(field) =>
			documentType === undefined ||
			field.document_type_ids === null ||
			(documentType !== null && field.document_type_ids.includes(documentType))
	);
}
