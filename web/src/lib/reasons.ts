/**
 * Reasons the API gives with a code (issue #83: a check's, a rule note's), in the user's
 * language. Every code has its message `reason_<code>`; a code without one fails `pnpm check`,
 * a message whose placeholders the API does not give fails a test (`x-reasons` of the OpenAPI
 * document). A code this UI does not know yet (a newer API) shows the API's English text.
 */
import type { components } from '#lib/api/schema.ts';
import { fieldLabel } from '#lib/describe.ts';
import { fieldTypeLabel, isFieldType } from '#lib/fields.ts';
import { labelOfKind } from '#lib/identifiers.ts';
import { formatDate, formatNumber, formatPercent, getLocale, regionalLocale } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { NODE_LABELS } from '#lib/node-labels.ts';
import { m } from '#lib/paraglide/messages.js';
import { own } from '#lib/utils.ts';

export type Reason = components['schemas']['ReasonOut'];
export type ReasonCode = components['schemas']['ReasonCode'];

/** How the API writes a parameter (`x-reasons`); a parameter without one is text. */
export type ReasonKind =
	| 'number'
	| 'percent'
	| 'date'
	| 'value'
	| 'names'
	| 'fields'
	| 'rule_values'
	| 'path'
	| 'reason'
	| 'list'
	| 'nodes'
	| 'thing'
	| 'action'
	| 'field_type'
	| 'identifier_kind';

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
	paperless_user_review: entry(m.reason_paperless_user_review),
	paperless_correspondent_review: entry(m.reason_paperless_correspondent_review),
	paperless_document_type_review: entry(m.reason_paperless_document_type_review),
	paperless_tag_review: entry(m.reason_paperless_tag_review),
	paperless_custom_field_review: entry(m.reason_paperless_custom_field_review),
	paperless_storage_path_review: entry(m.reason_paperless_storage_path_review),
	paperless_asn_review: entry(m.reason_paperless_asn_review),
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
	template_unreadable: entry(m.reason_template_unreadable, { type: 'field_type' }),
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
	no_similar: entry(m.reason_no_similar),
	input_missing: entry(m.reason_input_missing),
	input_too_short: entry(m.reason_input_too_short, { min: 'number' }),
	input_too_long: entry(m.reason_input_too_long, { max: 'number' }),
	input_too_few: entry(m.reason_input_too_few, { min: 'number' }),
	input_too_many: entry(m.reason_input_too_many, { max: 'number' }),
	input_too_small: entry(m.reason_input_too_small, { min: 'number' }),
	input_above: entry(m.reason_input_above, { min: 'number' }),
	input_too_large: entry(m.reason_input_too_large, { max: 'number' }),
	input_below: entry(m.reason_input_below, { max: 'number' }),
	input_choice: entry(m.reason_input_choice),
	input_not_id: entry(m.reason_input_not_id),
	input_not_date: entry(m.reason_input_not_date),
	input_not_datetime: entry(m.reason_input_not_datetime),
	input_not_number: entry(m.reason_input_not_number),
	input_not_integer: entry(m.reason_input_not_integer),
	input_not_boolean: entry(m.reason_input_not_boolean),
	input_not_text: entry(m.reason_input_not_text),
	input_not_list: entry(m.reason_input_not_list),
	input_not_object: entry(m.reason_input_not_object),
	input_unknown: entry(m.reason_input_unknown),
	input_pattern: entry(m.reason_input_pattern),
	input_invalid: entry(m.reason_input_invalid),
	in_use: entry(m.reason_in_use),
	name_taken: entry(m.reason_name_taken),
	topic_carried: entry(m.reason_topic_carried),
	choices_in_use: entry(m.reason_choices_in_use, { choices: 'list' }),
	values_outside_scope: entry(m.reason_values_outside_scope),
	title_pattern_uses_field: entry(m.reason_title_pattern_uses_field),
	type_has_values: entry(m.reason_type_has_values),
	tag_has_children: entry(m.reason_tag_has_children),
	tag_has_contacts: entry(m.reason_tag_has_contacts),
	tag_has_types: entry(m.reason_tag_has_types),
	topic_enabled_by: entry(m.reason_topic_enabled_by, { contacts: 'list' }),
	tag_used_by_rules: entry(m.reason_tag_used_by_rules, { rules: 'list' }),
	field_used_by_patterns: entry(m.reason_field_used_by_patterns, { types: 'list' }),
	field_used_by_rules: entry(m.reason_field_used_by_rules, { rules: 'list' }),
	field_key_taken: entry(m.reason_field_key_taken),
	identifier_of_person: entry(m.reason_identifier_of_person),
	identifier_of_contact: entry(m.reason_identifier_of_contact),
	profile_identifier_of_contact: entry(m.reason_profile_identifier_of_contact),
	name_of_contact: entry(m.reason_name_of_contact),
	name_too_close: entry(m.reason_name_too_close),
	logo_uploaded: entry(m.reason_logo_uploaded),
	logo_type: entry(m.reason_logo_type),
	logo_upload_type: entry(m.reason_logo_upload_type),
	training_needs_examples: entry(m.reason_training_needs_examples, {
		confirmed: 'number',
		needed: 'number'
	}),
	job_not_failed: entry(m.reason_job_not_failed),
	job_already_queued: entry(m.reason_job_already_queued),
	job_retry_in_document: entry(m.reason_job_retry_in_document),
	rule_follows_type: entry(m.reason_rule_follows_type),
	personal_space_undeletable: entry(m.reason_personal_space_undeletable),
	space_not_empty: entry(m.reason_space_not_empty),
	space_name_taken: entry(m.reason_space_name_taken),
	no_write_access_to_space: entry(m.reason_no_write_access_to_space),
	username_taken: entry(m.reason_username_taken),
	last_admin: entry(m.reason_last_admin),
	user_deletion_blocked: entry(m.reason_user_deletion_blocked, { spaces: 'list' }),
	display_name_taken: entry(m.reason_display_name_taken),
	username_of_other: entry(m.reason_username_of_other),
	lenses_limit: entry(m.reason_lenses_limit, { max: 'number' }),
	webhooks_limit: entry(m.reason_webhooks_limit, { max: 'number' }),
	model_call_taken: entry(m.reason_model_call_taken),
	model_call_admins: entry(m.reason_model_call_admins),
	open_fields: entry(m.reason_open_fields, { fields: 'fields' }),
	duplicate_of: entry(m.reason_duplicate_of),
	duplicate_unseen: entry(m.reason_duplicate_unseen),
	no_text_yet: entry(m.reason_no_text_yet),
	no_structure_yet: entry(m.reason_no_structure_yet),
	being_processed: entry(m.reason_being_processed),
	only_failed_retried: entry(m.reason_only_failed_retried),
	receive_not_repeatable: entry(m.reason_receive_not_repeatable),
	not_waiting_for_confirmation: entry(m.reason_not_waiting_for_confirmation),
	still_running: entry(m.reason_still_running, { nodes: 'nodes' }),
	no_text_to_extract: entry(m.reason_no_text_to_extract),
	no_vision_model: entry(m.reason_no_vision_model),
	cannot_skip: entry(m.reason_cannot_skip, { nodes: 'nodes' }),
	uncertain_before_filing: entry(m.reason_uncertain_before_filing),
	invalid_credentials: entry(m.reason_invalid_credentials),
	invalid_one_time_code: entry(m.reason_invalid_one_time_code),
	second_factor_required: entry(m.reason_second_factor_required),
	account_inactive: entry(m.reason_account_inactive),
	authentication_required: entry(m.reason_authentication_required),
	session_expired: entry(m.reason_session_expired),
	token_invalid: entry(m.reason_token_invalid),
	wrong_password: entry(m.reason_wrong_password),
	totp_already_on: entry(m.reason_totp_already_on),
	no_totp_setup: entry(m.reason_no_totp_setup),
	totp_off: entry(m.reason_totp_off),
	code_invalid: entry(m.reason_code_invalid),
	read_only_token: entry(m.reason_read_only_token),
	csrf_missing: entry(m.reason_csrf_missing),
	session_needed: entry(m.reason_session_needed),
	oidc_mismatch: entry(m.reason_oidc_mismatch),
	oidc_relink: entry(m.reason_oidc_relink),
	oidc_linked_elsewhere: entry(m.reason_oidc_linked_elsewhere),
	oidc_no_account: entry(m.reason_oidc_no_account),
	oidc_password_first: entry(m.reason_oidc_password_first),
	not_found: entry(m.reason_not_found, { kind: 'thing' }),
	page_not_found: entry(m.reason_page_not_found, { page: 'number' }),
	file_not_found: entry(m.reason_file_not_found, { file: 'thing' }),
	rule_version_not_found: entry(m.reason_rule_version_not_found, { number: 'number' }),
	name_empty: entry(m.reason_name_empty, { what: 'thing' }),
	name_too_long: entry(m.reason_name_too_long, { what: 'thing', max: 'number' }),
	admins_only: entry(m.reason_admins_only, { action: 'action' }),
	editors_only: entry(m.reason_editors_only, { action: 'action' }),
	admins_cannot: entry(m.reason_admins_cannot, { action: 'action' }),
	no_write_access_to_document: entry(m.reason_no_write_access_to_document),
	session_needed_create_user: entry(m.reason_session_needed_create_user),
	session_needed_role: entry(m.reason_session_needed_role),
	session_needed_profile: entry(m.reason_session_needed_profile),
	profile_own_only: entry(m.reason_profile_own_only),
	personal_space_describe: entry(m.reason_personal_space_describe),
	space_manage: entry(m.reason_space_manage),
	space_members_personal: entry(m.reason_space_members_personal),
	space_members: entry(m.reason_space_members),
	space_rule_apply: entry(m.reason_space_rule_apply),
	rule_disabled_deleted: entry(m.reason_rule_disabled_deleted, { kind: 'thing' }),
	rule_disabled_personal_space: entry(m.reason_rule_disabled_personal_space),
	rule_disabled_choice: entry(m.reason_rule_disabled_choice),
	rule_webhook_gone: entry(m.reason_rule_webhook_gone),
	rule_webhook_unreadable: entry(m.reason_rule_webhook_unreadable),
	task_no_answer: entry(m.reason_task_no_answer),
	task_error: entry(m.reason_task_error),
	task_invalid: entry(m.reason_task_invalid),
	task_too_large: entry(m.reason_task_too_large),
	task_undelivered: entry(m.reason_task_undelivered),
	task_run_over: entry(m.reason_task_run_over),
	task_run_stopped: entry(m.reason_task_run_stopped),
	rule_asks_on_arrival: entry(m.reason_rule_asks_on_arrival),
	skip_changed_meanwhile: entry(m.reason_skip_changed_meanwhile),
	skip_not_available: entry(m.reason_skip_not_available),
	not_iban: entry(m.reason_not_iban),
	not_vat_id: entry(m.reason_not_vat_id),
	not_customer_number: entry(m.reason_not_customer_number),
	not_of_kind: entry(m.reason_not_of_kind, { kind: 'identifier_kind' }),
	not_personnel_number: entry(m.reason_not_personnel_number),
	not_domain: entry(m.reason_not_domain),
	free_mail_domain: entry(m.reason_free_mail_domain),
	not_tax_id: entry(m.reason_not_tax_id),
	not_social_security_number: entry(m.reason_not_social_security_number),
	not_health_insurance_number: entry(m.reason_not_health_insurance_number),
	not_email_address: entry(m.reason_not_email_address),
	birth_date_too_early: entry(m.reason_birth_date_too_early, { date: 'date' }),
	birth_date_in_future: entry(m.reason_birth_date_in_future),
	alias_twice: entry(m.reason_alias_twice),
	person_too_many_aliases: entry(m.reason_person_too_many_aliases, { max: 'number' }),
	person_too_many_identifiers: entry(m.reason_person_too_many_identifiers, { max: 'number' }),
	display_name_is_alias: entry(m.reason_display_name_is_alias),
	too_many_groups: entry(m.reason_too_many_groups, { max: 'number' }),
	too_many_topics: entry(m.reason_too_many_topics, { max: 'number' }),
	identifier_topic_not_enabled: entry(m.reason_identifier_topic_not_enabled),
	alias_is_name: entry(m.reason_alias_is_name),
	contact_too_many_aliases: entry(m.reason_contact_too_many_aliases, { max: 'number' }),
	contact_too_many_identifiers: entry(m.reason_contact_too_many_identifiers, { max: 'number' }),
	only_numbers_name_users: entry(m.reason_only_numbers_name_users),
	identifier_taken: entry(m.reason_identifier_taken),
	title_pattern_too_long: entry(m.reason_title_pattern_too_long, { max: 'number' }),
	description_too_long: entry(m.reason_description_too_long, { max: 'number' }),
	title_pattern_unknown: entry(m.reason_title_pattern_unknown),
	tag_own_parent: entry(m.reason_tag_own_parent),
	groups_manual: entry(m.reason_groups_manual),
	tag_wrong_scope: entry(m.reason_tag_wrong_scope, { scope: 'thing', expected: 'thing' }),
	tag_parent_other_scope: entry(m.reason_tag_parent_other_scope),
	tag_under_own_child: entry(m.reason_tag_under_own_child),
	tag_too_deep: entry(m.reason_tag_too_deep, { max: 'number' }),
	field_global_required: entry(m.reason_field_global_required),
	field_typed_required: entry(m.reason_field_typed_required),
	field_required_own_types: entry(m.reason_field_required_own_types),
	choice_needs_choices: entry(m.reason_choice_needs_choices),
	choices_not_unique: entry(m.reason_choices_not_unique),
	only_choice_fields_choices: entry(m.reason_only_choice_fields_choices),
	field_needs_type: entry(m.reason_field_needs_type),
	field_is_global: entry(m.reason_field_is_global),
	field_only_this_type: entry(m.reason_field_only_this_type),
	field_not_for_type: entry(m.reason_field_not_for_type),
	not_a_url: entry(m.reason_not_a_url),
	url_not_http: entry(m.reason_url_not_http),
	receipt_in_future: entry(m.reason_receipt_in_future),
	personal_space_name: entry(m.reason_personal_space_name),
	personal_space_editor: entry(m.reason_personal_space_editor),
	space_needs_editor: entry(m.reason_space_needs_editor),
	password_too_short: entry(m.reason_password_too_short, { min: 'number' }),
	password_too_long: entry(m.reason_password_too_long, { max: 'number' }),
	password_is_username: entry(m.reason_password_is_username),
	expiry_in_past: entry(m.reason_expiry_in_past),
	url_length: entry(m.reason_url_length, { max: 'number' }),
	url_spaces: entry(m.reason_url_spaces),
	url_invalid: entry(m.reason_url_invalid),
	url_scheme: entry(m.reason_url_scheme),
	url_no_host: entry(m.reason_url_no_host),
	url_credentials: entry(m.reason_url_credentials),
	url_fragment: entry(m.reason_url_fragment),
	header_name_invalid: entry(m.reason_header_name_invalid),
	header_reserved: entry(m.reason_header_reserved),
	header_value_invalid: entry(m.reason_header_value_invalid, { max: 'number' }),
	header_twice: entry(m.reason_header_twice),
	headers_limit: entry(m.reason_headers_limit, { max: 'number' }),
	header_value_missing: entry(m.reason_header_value_missing),
	icon_invalid: entry(m.reason_icon_invalid, { max: 'number' }),
	colour_invalid: entry(m.reason_colour_invalid),
	card_field_unknown: entry(m.reason_card_field_unknown),
	due_field_not_date: entry(m.reason_due_field_not_date),
	sort_field_invalid: entry(m.reason_sort_field_invalid),
	pattern_invalid: entry(m.reason_pattern_invalid),
	search_no_embeddings: entry(m.reason_search_no_embeddings),
	search_embed_timeout: entry(m.reason_search_embed_timeout, { seconds: 'number' }),
	search_embed_failed: entry(m.reason_search_embed_failed),
	search_embed_dimensions: entry(m.reason_search_embed_dimensions, {
		got: 'number',
		wanted: 'number'
	}),
	search_index_unavailable: entry(m.reason_search_index_unavailable),
	search_not_configured: entry(m.reason_search_not_configured)
};

/** The nouns the API names things by (the kind `thing`), in the user's language. */
const THINGS: Record<string, () => string> = {
	document: m.thing_document,
	contact: m.thing_contact,
	'document type': m.thing_document_type,
	tag: m.thing_tag,
	field: m.thing_field,
	space: m.thing_space,
	user: m.thing_user,
	profile: m.thing_profile,
	rule: m.thing_rule,
	'rule version': m.thing_rule_version,
	'rule application': m.thing_rule_application,
	webhook: m.thing_webhook,
	'webhook delivery': m.thing_webhook_delivery,
	lens: m.thing_lens,
	job: m.thing_job,
	object: m.thing_object,
	credential: m.thing_credential,
	session: m.thing_session,
	'external identity': m.thing_external_identity,
	'classifier model': m.thing_classifier_model,
	'personal space of user': m.thing_personal_space_of_user,
	'logo of contact': m.thing_logo_of_contact,
	'identity provider': m.thing_identity_provider,
	original: m.thing_original,
	archive: m.thing_archive,
	preview: m.thing_preview,
	page: m.thing_page,
	name: m.thing_name,
	title: m.thing_title,
	'space name': m.thing_space_name,
	'webhook name': m.thing_webhook_name,
	username: m.thing_username,
	'token name': m.thing_token_name,
	'rule name': m.thing_rule_name,
	'lens name': m.thing_lens_name,
	'display name': m.thing_display_name,
	alias: m.thing_alias,
	choice: m.thing_choice,
	subject: m.thing_subject,
	issuer: m.thing_issuer,
	'original filename': m.thing_original_filename,
	'media type': m.thing_media_type,
	'document tag': m.tag_kind_document,
	'contact group': m.tag_kind_contact,
	'document type group': m.tag_kind_type,
	topic: m.tag_kind_topic
};

/** What only some may do (the kind `action`, the API's `Action`), in the user's language. */
const ACTIONS: Record<string, () => string> = {
	manage_users: m.action_manage_users,
	change_master_data: m.action_change_master_data,
	see_all_inboxes: m.action_see_all_inboxes,
	count_all_documents: m.action_count_all_documents,
	list_all_documents: m.action_list_all_documents,
	search_all_documents: m.action_search_all_documents,
	list_all_rules: m.action_list_all_rules,
	list_all_spaces: m.action_list_all_spaces,
	train_classifier: m.action_train_classifier,
	rebuild_index: m.action_rebuild_index,
	retry_jobs: m.action_retry_jobs,
	check_index: m.action_check_index,
	reparse_all: m.action_reparse_all,
	make_global_rules: m.action_make_global_rules,
	change_global_rules: m.action_change_global_rules,
	make_space_rules: m.action_make_space_rules,
	change_unconfirmed: m.action_change_unconfirmed,
	give_upload_metadata: m.action_give_upload_metadata,
	upload_for_others: m.action_upload_for_others,
	control_processing: m.action_control_processing,
	read_processing_log: m.action_read_processing_log,
	read_exchanges: m.action_read_exchanges,
	review_document: m.action_review_document,
	move_document: m.action_move_document,
	delete_document: m.action_delete_document,
	reset_own_password: m.action_reset_own_password,
	turn_off_own_totp: m.action_turn_off_own_totp
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
			return formatPercent(Number(value));
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
		case 'list':
			return new Intl.ListFormat(listLocale(), { type: 'conjunction' }).format(
				items(value).map((name) => quoted(String(name)))
			);
		case 'thing':
			return own(THINGS, String(value))?.() ?? String(value);
		case 'action':
			return own(ACTIONS, String(value))?.() ?? String(value);
		case 'field_type':
			return isFieldType(value) ? fieldTypeLabel(value) : String(value);
		case 'identifier_kind':
			return labelOfKind(String(value));
		case 'nodes':
			return new Intl.ListFormat(listLocale(), { type: 'conjunction' }).format(
				items(value).map((node) => {
					const label = NODE_LABELS[String(node) as keyof typeof NODE_LABELS];
					return label ? label() : String(node);
				})
			);
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
	return code === 'text' || code === 'error' || Object.hasOwn(REASONS, code);
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
