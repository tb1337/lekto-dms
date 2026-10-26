/** Texts for values in a change: ids become names, the rest is shown plainly. */
import { isIsoDay } from '#lib/dates.ts';
import { isMoney, isPeriod } from '#lib/fields.ts';
import { formatDate, formatMoney } from '#lib/i18n.ts';
import { spaceNameFor, userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { writePeriod } from '#lib/periods.ts';
import { session } from '#lib/session.svelte.ts';
import { own } from '#lib/utils.ts';

const FIELD_LABELS: Record<string, () => string> = {
	title: m.field_title,
	contact: m.field_contact,
	topic: m.field_topic,
	document_type: m.field_document_type,
	tags: m.field_tags,
	document_date: m.field_date,
	space: m.field_space,
	correspondent: m.field_contact,
	// A person's verdict on a document's facts (#145).
	facts: m.facts_title
};

/** The name of a field in a change: `field:<id>` shows the field's name. */
export function fieldLabel(field: string, lookup: Lookup | null): string {
	if (field.startsWith('field:')) {
		const id = field.slice('field:'.length);
		return lookup?.fields.find((entry) => entry.id === id)?.name ?? field;
	}
	return own(FIELD_LABELS, field)?.() ?? field;
}

/** A value as the user reads it. */
export function describeValue(value: unknown, lookup: Lookup | null): string {
	if (value === null || value === undefined || value === '') return m.value_unset();
	if (Array.isArray(value)) return value.map((entry) => describeValue(entry, lookup)).join(', ');
	if (typeof value === 'boolean') return value ? m.value_yes() : m.value_no();
	if (isMoney(value)) return formatMoney(value.amount, value.currency);
	if (isPeriod(value)) return writePeriod(value.start, value.end);
	if (typeof value === 'object') return JSON.stringify(value);
	const text = String(value);
	if (lookup) {
		const named = [...lookup.contacts, ...lookup.documentTypes, ...lookup.tags].find(
			(entry) => entry.id === text
		);
		if (named) return named.name;
		// A space, also another user's personal one the caller is no member of.
		const space = spaceNameFor(text, lookup, session.user?.id, '');
		if (space) return space;
		const user = lookup.users.find((entry) => entry.id === text);
		if (user) return userLabel(user);
	}
	return isIsoDay(text) ? formatDate(text) : text;
}
