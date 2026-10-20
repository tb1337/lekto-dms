/**
 * What the documents of the list stand under. Without a lens (`sort`), by the month of the
 * sort's date as the list runs (`byMonth`), nothing while it sorts by title or relevance. A lens
 * groups by the month of the document date (newest first), by how soon its deadline is due
 * (overdue, within seven days, later), by type or by contact (by name); each in a group of its
 * own, those without one last, the documents of a group in the order of the list.
 */

import { dueOf } from '#lib/card-fields.ts';
import { formatDate } from '#lib/i18n.ts';
import type { Grouping } from '#lib/lenses.ts';
import { byMonth, type Sort } from '#lib/listing.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export interface Group<T> {
	key: string;
	/** The heading; null: no heading (the list is not grouped). */
	label: string | null;
	/** How the heading looks: a deadline passed, near, or neither. */
	tone: 'overdue' | 'soon' | null;
	items: T[];
}

export interface Grouped {
	document_date?: string | null;
	created_at: string;
	contact_id?: string | null;
	document_type_id?: string | null;
	fields?: Record<string, unknown>;
}

export interface GroupContext {
	sort: Sort;
	/** The lens's deadline field. */
	dueField: string | null;
	today: Date;
	lookup: Lookup | null;
}

function monthLabel(month: string | null): string | null {
	if (month === null) return null;
	if (month === '') return m.documents_no_date();
	const [year, number] = month.split('-').map(Number);
	return formatDate(new Date(year, number - 1, 1), { month: 'long', year: 'numeric' });
}

/** Buckets of `items` by `keyOf`, in the order of `order` (keys not in it by label), `''`
 * (none) last. */
function buckets<T>(
	items: readonly T[],
	keyOf: (item: T) => string,
	labelOf: (key: string) => string,
	toneOf: (key: string) => Group<T>['tone'] = () => null,
	order: readonly string[] = []
): Group<T>[] {
	const found = new Map<string, T[]>();
	for (const item of items) {
		const key = keyOf(item);
		found.set(key, [...(found.get(key) ?? []), item]);
	}
	const rank = (key: string) => (key === '' ? 2 : order.includes(key) ? 0 : 1);
	return [...found.entries()]
		.map(([key, grouped]) => ({ key, label: labelOf(key), tone: toneOf(key), items: grouped }))
		.toSorted(
			(a, b) =>
				rank(a.key) - rank(b.key) ||
				order.indexOf(a.key) - order.indexOf(b.key) ||
				a.label.localeCompare(b.label)
		);
}

const DUE_ORDER = ['overdue', 'soon', 'later'] as const;

export function groupDocuments<T>(
	items: readonly T[],
	grouping: Grouping | 'sort',
	documentOf: (item: T) => Grouped,
	context: GroupContext
): Group<T>[] {
	switch (grouping) {
		case 'none':
			return items.length > 0 ? [{ key: 'all', label: null, tone: null, items: [...items] }] : [];
		case 'due':
			return buckets(
				items,
				(item) => {
					const day = context.dueField ? documentOf(item).fields?.[context.dueField] : null;
					return typeof day === 'string' && day ? dueOf(day, context.today).state : '';
				},
				(key) =>
					({
						overdue: m.lens_group_overdue(),
						soon: m.lens_group_soon(),
						later: m.lens_group_later()
					})[key] ?? m.lens_group_no_due(),
				(key) => (key === 'overdue' || key === 'soon' ? key : null),
				DUE_ORDER
			);
		case 'document_type':
			return buckets(
				items,
				(item) => documentOf(item).document_type_id ?? '',
				(key) =>
					context.lookup?.documentTypes.find((entry) => entry.id === key)?.name ??
					(key ? key : m.lens_group_no_type())
			);
		case 'contact':
			return buckets(
				items,
				(item) => documentOf(item).contact_id ?? '',
				(key) =>
					context.lookup?.contacts.find((entry) => entry.id === key)?.name ??
					(key ? key : m.lens_group_no_contact())
			);
		case 'month': {
			const monthOf = (item: T) => documentOf(item).document_date?.slice(0, 7) ?? '';
			const months = [...new Set(items.map(monthOf))].toSorted().reverse();
			return buckets(items, monthOf, (key) => monthLabel(key) ?? '', undefined, months);
		}
		case 'sort':
			return byMonth(items, context.sort, documentOf).map((group) => ({
				key: `${group.start}`,
				label: monthLabel(group.month),
				tone: null,
				items: group.items
			}));
	}
}
