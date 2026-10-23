/**
 * Reasons the API gives with a code (issue #83: a check's, a rule note's), in the user's
 * language. Every code has its message `reason_<code>`; a code without one fails `pnpm check`,
 * a message whose placeholders the API does not give fails a test (`x-reasons` of the OpenAPI
 * document). A code this UI does not know yet (a newer API) shows the API's English text.
 */
import type { components } from '#lib/api/schema.ts';
import { fieldLabel } from '#lib/describe.ts';
import { formatDate, formatNumber, getLocale, regionalLocale } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type Reason = components['schemas']['ReasonOut'];
export type ReasonCode = components['schemas']['ReasonCode'];

/** How the API writes a parameter (`x-reasons`); a parameter without one is text. */
export type ReasonKind =
	'number' | 'percent' | 'date' | 'value' | 'names' | 'fields' | 'rule_values' | 'path' | 'reason';

/** A message of `#lib/paraglide/messages.js`, whatever it takes. */
type Message = (inputs: never) => string;

export interface ReasonEntry {
	message: (inputs: Record<string, string>) => string;
	kinds: Readonly<Record<string, ReasonKind>>;
}

export interface ReasonOptions {
	/** The name of a check field (`contact`, `field:<id>`) for the kind `fields`. */
	field?: (name: string) => string;
}

function entry(message: Message, kinds: Record<string, ReasonKind> = {}): ReasonEntry {
	return { message: message as (inputs: Record<string, string>) => string, kinds };
}

/** Every code but `text` and `error`, which show what they hold as it is. */
export const REASONS: Record<Exclude<ReasonCode, 'text' | 'error'>, ReasonEntry> = {
	signals_disagree: entry(m.reason_signals_disagree, { names: 'names' }),
	only_suggested: entry(m.reason_only_suggested),
	one_signal_only: entry(m.reason_one_signal_only),
	only_identifier: entry(m.reason_only_identifier),
	contact_is_recipient: entry(m.reason_contact_is_recipient),
	contact_identifiers_several: entry(m.reason_contact_identifiers_several),
	contact_new_proposed: entry(m.reason_contact_new_proposed),
	contact_none: entry(m.reason_contact_none),
	contact_none_no_model: entry(m.reason_contact_none_no_model),
	contact_not_in_text: entry(m.reason_contact_not_in_text),
	sender_not_a_contact: entry(m.reason_sender_not_a_contact),
	sender_matches_several: entry(m.reason_sender_matches_several),
	sender_only_similar: entry(m.reason_sender_only_similar),
	type_new_proposed: entry(m.reason_type_new_proposed),
	type_none: entry(m.reason_type_none),
	topic_without_contact: entry(m.reason_topic_without_contact),
	topic_none: entry(m.reason_topic_none),
	topic_contact_suggested: entry(m.reason_topic_contact_suggested),
	space_chosen_by_person: entry(m.reason_space_chosen_by_person),
	space_named_unseen: entry(m.reason_space_named_unseen),
	space_stays_for_named: entry(m.reason_space_stays_for_named),
	space_shows_more: entry(m.reason_space_shows_more),
	space_hand_over: entry(m.reason_space_hand_over),
	space_uploader_unseen: entry(m.reason_space_uploader_unseen),
	space_other: entry(m.reason_space_other),
	spaces_disagree: entry(m.reason_spaces_disagree),
	date_none: entry(m.reason_date_none),
	date_none_from_model: entry(m.reason_date_none_from_model, { why: 'reason' }),
	not_a_date: entry(m.reason_not_a_date),
	date_implausible: entry(m.reason_date_implausible, { date: 'date' }),
	same_as_document_date: entry(m.reason_same_as_document_date),
	not_a_period: entry(m.reason_not_a_period),
	period_implausible: entry(m.reason_period_implausible),
	period_no_year: entry(m.reason_period_no_year),
	same_day_as_document_date: entry(m.reason_same_day_as_document_date),
	field_set_by_hand: entry(m.reason_field_set_by_hand),
	field_by_hand_missing: entry(m.reason_field_by_hand_missing),
	field_not_found: entry(m.reason_field_not_found),
	field_not_read_no_model: entry(m.reason_field_not_read_no_model),
	value_invalid: entry(m.reason_value_invalid),
	quote_not_in_text: entry(m.reason_quote_not_in_text),
	quote_missing: entry(m.reason_quote_missing),
	quote_without_value: entry(m.reason_quote_without_value),
	quote_too_short: entry(m.reason_quote_too_short),
	date_not_in_text: entry(m.reason_date_not_in_text),
	period_not_in_text: entry(m.reason_period_not_in_text),
	amount_not_in_text: entry(m.reason_amount_not_in_text),
	currency_not_in_text: entry(m.reason_currency_not_in_text),
	number_not_in_text: entry(m.reason_number_not_in_text),
	link_not_in_text: entry(m.reason_link_not_in_text),
	text_not_in_text: entry(m.reason_text_not_in_text),
	value_read_unsure: entry(m.reason_value_read_unsure, { unsure: 'number' }),
	page_poorly_read: entry(m.reason_page_poorly_read, { page: 'number', share: 'percent' }),
	page_poorly_read_content: entry(m.reason_page_poorly_read_content, {
		page: 'number',
		share: 'percent'
	}),
	surroundings_poorly_read: entry(m.reason_surroundings_poorly_read, {
		unsure: 'number',
		words: 'number'
	}),
	source_lacks_contact: entry(m.reason_source_lacks_contact),
	source_lacks_document_type: entry(m.reason_source_lacks_document_type),
	source_lacks_document_date: entry(m.reason_source_lacks_document_date),
	field_does_not_apply: entry(m.reason_field_does_not_apply),
	field_gone: entry(m.reason_field_gone),
	contact_gone: entry(m.reason_contact_gone),
	document_type_gone: entry(m.reason_document_type_gone),
	topic_gone: entry(m.reason_topic_gone),
	tag_gone: entry(m.reason_tag_gone),
	space_gone: entry(m.reason_space_gone),
	tag_is_group: entry(m.reason_tag_is_group),
	rule_other_space: entry(m.reason_rule_other_space),
	space_no_right_any_more: entry(m.reason_space_no_right_any_more),
	space_no_right: entry(m.reason_space_no_right),
	space_widens_unconfirmed: entry(m.reason_space_widens_unconfirmed, { fields: 'fields' }),
	space_widens_needs_confirmed: entry(m.reason_space_widens_needs_confirmed, { fields: 'fields' }),
	review_on_arrival_only: entry(m.reason_review_on_arrival_only),
	review_confirmed: entry(m.reason_review_confirmed),
	rules_disagree: entry(m.reason_rules_disagree, { values: 'rule_values' }),
	value_other_not_accepted: entry(m.reason_value_other_not_accepted, { value: 'value' }),
	person_decided_field: entry(m.reason_person_decided_field),
	rule_value_on_unconfirmed: entry(m.reason_rule_value_on_unconfirmed, { value: 'value' }),
	model_value_other: entry(m.reason_model_value_other, { value: 'value' }),
	rules_value_on_unconfirmed: entry(m.reason_rules_value_on_unconfirmed, { value: 'value' }),
	rules_model_value_other: entry(m.reason_rules_model_value_other, { value: 'value' }),
	topic_person_chose: entry(m.reason_topic_person_chose),
	topic_no_contact: entry(m.reason_topic_no_contact),
	topic_not_enabled: entry(m.reason_topic_not_enabled),
	tag_added_and_removed: entry(m.reason_tag_added_and_removed),
	tag_removed_by_person: entry(m.reason_tag_removed_by_person),
	tag_set_by_person: entry(m.reason_tag_set_by_person),
	tag_above_kept: entry(m.reason_tag_above_kept),
	title_empty: entry(m.reason_title_empty),
	title_yields: entry(m.reason_title_yields),
	value_empty: entry(m.reason_value_empty),
	template_missing_value: entry(m.reason_template_missing_value),
	node_attempts_exhausted: entry(m.reason_node_attempts_exhausted, { attempts: 'number' }),
	node_crashed: entry(m.reason_node_crashed),
	file_not_pdf_or_image: entry(m.reason_file_not_pdf_or_image),
	file_damaged: entry(m.reason_file_damaged),
	file_not_processable: entry(m.reason_file_not_processable),
	pdf_encrypted: entry(m.reason_pdf_encrypted),
	pdf_unreadable: entry(m.reason_pdf_unreadable),
	pdf_unreadable_detail: entry(m.reason_pdf_unreadable_detail),
	image_unreadable: entry(m.reason_image_unreadable),
	image_unreadable_detail: entry(m.reason_image_unreadable_detail),
	document_no_pages: entry(m.reason_document_no_pages),
	ocr_failed: entry(m.reason_ocr_failed, { problem: 'reason' }),
	text_unreadable: entry(m.reason_text_unreadable),
	signature_dropped: entry(m.reason_signature_dropped),
	colours_converted: entry(m.reason_colours_converted),
	not_pdfa: entry(m.reason_not_pdfa),
	archive_not_pdfa: entry(m.reason_archive_not_pdfa),
	vision_read: entry(m.reason_vision_read),
	vision_not_configured: entry(m.reason_vision_not_configured),
	no_text: entry(m.reason_no_text),
	answer_unfit: entry(m.reason_answer_unfit),
	nothing_recognised: entry(m.reason_nothing_recognised),
	master_data_changed: entry(m.reason_master_data_changed),
	metadata_unfit: entry(m.reason_metadata_unfit),
	taken_over: entry(m.reason_taken_over),
	space_changed_meanwhile: entry(m.reason_space_changed_meanwhile),
	rules_back_and_forth: entry(m.reason_rules_back_and_forth, { spaces: 'path' }),
	rules_change_unfit: entry(m.reason_rules_change_unfit),
	signal_did_not_run: entry(m.reason_signal_did_not_run),
	no_language_model: entry(m.reason_no_language_model),
	no_document_text: entry(m.reason_no_document_text),
	no_classifier: entry(m.reason_no_classifier),
	classifier_unusable: entry(m.reason_classifier_unusable),
	classifier_untrained: entry(m.reason_classifier_untrained),
	neighbours_off: entry(m.reason_neighbours_off),
	no_embedding_index: entry(m.reason_no_embedding_index),
	text_not_embedded: entry(m.reason_text_not_embedded),
	vector_misfit: entry(m.reason_vector_misfit),
	no_uploader: entry(m.reason_no_uploader),
	index_unavailable: entry(m.reason_index_unavailable),
	no_similar: entry(m.reason_no_similar)
};

function listLocale(): string {
	return regionalLocale(getLocale());
}

function quoted(text: string): string {
	return m.rule_quoted({ text });
}

/** A field's value as a reason shows it: yes or no, not set, a name or text quoted as the
 * language quotes. */
function writeValue(value: unknown): string {
	if (value === null || value === undefined) return m.value_unset();
	if (typeof value === 'boolean') return value ? m.value_yes() : m.value_no();
	const text = String(value);
	const inner = /^'(.*)'$/s.exec(text);
	return inner ? quoted(inner[1]) : text;
}

function items(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [value];
}

function write(value: unknown, kind: ReasonKind | undefined, options: ReasonOptions): string {
	switch (kind) {
		case 'number':
			return formatNumber(Number(value));
		case 'percent':
			return formatNumber(Number(value), { style: 'percent', maximumFractionDigits: 0 });
		case 'date':
			return formatDate(String(value));
		case 'value':
			return writeValue(value);
		case 'names':
			return new Intl.ListFormat(listLocale(), { type: 'disjunction' }).format(
				items(value).map((name) => quoted(String(name)))
			);
		case 'fields':
			return new Intl.ListFormat(listLocale(), { type: 'conjunction' }).format(
				items(value).map((name) => options.field?.(String(name)) ?? String(name))
			);
		case 'rule_values':
			return items(value)
				.map((item) => {
					const { rule, value: set } = (item ?? {}) as { rule?: unknown; value?: unknown };
					return `${quoted(String(rule))}: ${writeValue(set)}`;
				})
				.join(', ');
		case 'path':
			return items(value).map(String).join(' → ');
		case 'reason':
			return nested(value, options);
		default:
			return String(value ?? '');
	}
}

/** A reason inside another (its parameter of the kind `reason`); its English text where this UI
 * does not know its code. */
function nested(value: unknown, options: ReasonOptions): string {
	const reason = value as Reason | null;
	if (!reason || typeof reason !== 'object' || !known(reason.code)) return String(value ?? '');
	return reasonText(reason, options);
}

function known(code: string): code is ReasonCode {
	return code === 'text' || code === 'error' || code in REASONS;
}

/** One reason in the user's language. */
export function reasonText(reason: Reason, options: ReasonOptions = {}): string {
	const params = reason.params;
	let text: string;
	if (reason.code === 'text') text = String(params.text ?? '');
	else if (reason.code === 'error') text = String(params.detail ?? '');
	else {
		const { message, kinds } = REASONS[reason.code];
		const inputs = Object.fromEntries(
			Object.entries(params).map(([name, value]) => [name, write(value, kinds[name], options)])
		);
		text = message(inputs);
	}
	if (reason.subject) text = m.reason_about({ subject: reason.subject, text });
	if (reason.rule) text = m.reason_by_rule({ rule: reason.rule, text });
	if (reason.field) {
		text = m.reason_field({ field: options.field?.(reason.field) ?? reason.field, text });
	}
	return text;
}

/**
 * The reasons in the user's language, joined as the API joins them; `fallback` (the API's
 * English text) without reasons or where a code is unknown here.
 */
export function reasonsText(
	reasons: readonly Reason[] | null | undefined,
	fallback: string | null | undefined,
	options: ReasonOptions = {}
): string | null {
	if (!reasons?.length || !reasons.every((reason) => known(reason.code))) return fallback ?? null;
	return reasons.map((reason) => reasonText(reason, options)).join('; ');
}

/** Options that name check fields as the UI does (`field:<id>` by the field's name). */
export function labelled(lookup: Lookup | null): ReasonOptions {
	return { field: (name) => fieldLabel(name, lookup) };
}

/**
 * A reason a log entry's output holds beside its English text (`abstained_reason` beside
 * `abstained`, `problem_reason` beside `problem`), in the user's language; the text without it.
 */
export function outputReasonText(
	reason: unknown,
	fallback: unknown,
	options: ReasonOptions = {}
): string | null {
	const text = typeof fallback === 'string' && fallback ? fallback : null;
	if (!reason || typeof reason !== 'object' || !('code' in reason)) return text;
	return reasonsText([reason as Reason], text, options);
}
