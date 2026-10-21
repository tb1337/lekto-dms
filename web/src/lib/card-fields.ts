/**
 * The fields a lens shows on its cards (up to three, in its order) and its deadline. An amount
 * and the deadline share a line, the amount on the left, how soon it is due on the right; the
 * other fields stand as name and value below. A field the document has no value for is left
 * out. The deadline is yellow from seven days before and red once passed, with an icon and
 * words, never by colour alone.
 */

import { describeValue } from '#lib/describe.ts';
import { isMoney } from '#lib/fields.ts';
import { formatDate, formatMoney, formatNumber } from '#lib/i18n.ts';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type DueState = 'overdue' | 'soon' | 'later';

export interface Due {
	state: DueState;
	/** Whole days from today to the deadline; negative once passed. */
	days: number;
	/** The day, `YYYY-MM-DD`. */
	day: string;
}

const SOON = 7;

/** How soon `day` (`YYYY-MM-DD`) is due as of `today`, by calendar days in the browser's time. */
export function dueOf(day: string, today: Date): Due {
	const [year, month, date] = day.split('-').map(Number);
	const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
	const days = Math.round((Date.UTC(year, month - 1, date) - start) / 86_400_000);
	return { state: days < 0 ? 'overdue' : days <= SOON ? 'soon' : 'later', days, day };
}

/** The words for a deadline: "since 4 days", "tomorrow", "in 5 days", "due 15.11.". */
export function dueText(due: Due): string {
	if (due.days < -1) return m.due_overdue({ count: formatNumber(-due.days) });
	if (due.days === -1) return m.due_overdue_one();
	if (due.days === 0) return m.due_today();
	if (due.days === 1) return m.due_tomorrow();
	if (due.days <= SOON) return m.due_in({ count: formatNumber(due.days) });
	return m.due_on({ date: formatDate(due.day, { day: '2-digit', month: '2-digit' }) });
}

/** A value of a field as the card shows it. */
export function fieldText(value: unknown, field: FieldDefinition): string {
	if (field.data_type === 'number' && typeof value === 'string' && value !== '') {
		const number = Number(value);
		if (Number.isFinite(number)) return formatNumber(number);
	}
	if (isMoney(value)) return formatMoney(value.amount, value.currency);
	return describeValue(value, null);
}

export type CardLine =
	| { kind: 'pay'; amount: string | null; due: Due | null; dueName: string }
	| { kind: 'value'; name: string; text: string; due: Due | null };

/**
 * The lines of a card for `values` (a document's fields by id): the fields of `fields` in
 * their order, the deadline `dueId` (when among them) beside the first amount.
 */
export function cardLines(
	values: Record<string, unknown> | undefined,
	fields: readonly FieldDefinition[],
	dueId: string | null,
	today: Date
): CardLine[] {
	const has = (id: string) => {
		const value = values?.[id];
		return value !== undefined && value !== null && value !== '';
	};
	const dueField = fields.find((field) => field.id === dueId && field.data_type === 'date');
	const due = dueField && has(dueField.id) ? dueOf(String(values?.[dueField.id]), today) : null;
	const amount = fields.find((field) => field.data_type === 'amount');
	const paired = dueField !== undefined && amount !== undefined;
	const lines: CardLine[] = [];
	if (paired && (has(amount.id) || due)) {
		lines.push({
			kind: 'pay',
			amount: has(amount.id) ? fieldText(values?.[amount.id], amount) : null,
			due,
			dueName: dueField.name
		});
	}
	for (const field of fields) {
		if (paired && (field === amount || field === dueField)) continue;
		if (!has(field.id)) continue;
		lines.push({
			kind: 'value',
			name: field.name,
			text: fieldText(values?.[field.id], field),
			due: field === dueField ? due : null
		});
	}
	return lines;
}
