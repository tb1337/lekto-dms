/**
 * The filters of the document view (list and search), as they stand in the page's URL. No lane:
 * where a document stands is the inbox's matter (the API keeps the filter).
 */

export interface Filters {
	/** One of them (each repeats in the URL). */
	contacts: string[];
	types: string[];
	/** Each with the tags below it; all of them. */
	tags: string[];
	/** Documents whose contact (type) is in each group or one below it. */
	contactGroups: string[];
	typeGroups: string[];
	/** Documents with one of these topics or one below it (a document has one topic). */
	topics: string[];
	/** One of them. */
	spaces: string[];
	/** Documents with a value for this field. */
	field: string | null;
	/** The document date lies between them, both days included (ISO days; either open). */
	dateFrom: string | null;
	dateTo: string | null;
}

export const NO_FILTERS: Filters = {
	contacts: [],
	types: [],
	tags: [],
	contactGroups: [],
	typeGroups: [],
	topics: [],
	spaces: [],
	field: null,
	dateFrom: null,
	dateTo: null
};

const LISTS = {
	contacts: 'contact',
	types: 'type',
	tags: 'tag',
	contactGroups: 'contact_group',
	typeGroups: 'type_group',
	topics: 'topic',
	spaces: 'space'
} as const;

/** The filters in `params`; empty values (`?contact=`) count as none. Whom the list covers is no
 * filter but a setting (`scope`). */
export function parseFilters(params: URLSearchParams): Filters {
	const all = (key: string) => params.getAll(key).filter((value) => value !== '');
	return {
		contacts: all(LISTS.contacts),
		types: all(LISTS.types),
		tags: all(LISTS.tags),
		contactGroups: all(LISTS.contactGroups),
		typeGroups: all(LISTS.typeGroups),
		topics: all(LISTS.topics),
		spaces: all(LISTS.spaces),
		field: params.get('field') || null,
		dateFrom: day(params.get('date_from')),
		dateTo: day(params.get('date_to'))
	};
}

/** Write the filters into `params` (other parameters stay). */
export function writeFilters(params: URLSearchParams, filters: Filters): URLSearchParams {
	for (const key of [...Object.values(LISTS), 'field', 'date_from', 'date_to']) {
		params.delete(key);
	}
	for (const [list, key] of Object.entries(LISTS) as [keyof typeof LISTS, string][]) {
		for (const id of filters[list]) params.append(key, id);
	}
	if (filters.field) params.set('field', filters.field);
	if (filters.dateFrom) params.set('date_from', filters.dateFrom);
	if (filters.dateTo) params.set('date_to', filters.dateTo);
	return params;
}

/** The query of the API for these filters; `allUsers` from the scope setting. */
export function apiQuery(filters: Filters, allUsers = false) {
	const list = (ids: string[]) => (ids.length > 0 ? ids : undefined);
	return {
		contact_id: list(filters.contacts),
		document_type_id: list(filters.types),
		tag_id: list(filters.tags),
		contact_group_id: list(filters.contactGroups),
		document_type_group_id: list(filters.typeGroups),
		topic_id: list(filters.topics),
		space_id: list(filters.spaces),
		field_id: filters.field ?? undefined,
		document_date_from: filters.dateFrom ?? undefined,
		document_date_to: filters.dateTo ?? undefined,
		all_users: allUsers || undefined
	};
}

/** Whether a filter narrows the list. */
export function isFiltered(filters: Filters): boolean {
	return Boolean(
		filters.field ||
		filters.dateFrom ||
		filters.dateTo ||
		Object.keys(LISTS).some((list) => filters[list as keyof typeof LISTS].length > 0)
	);
}

/** A whole year or month of the document date, as the filters hold it. */
export function yearPeriod(year: number): Pick<Filters, 'dateFrom' | 'dateTo'> {
	return { dateFrom: `${year}-01-01`, dateTo: `${year}-12-31` };
}

/** `month` as `2026-09`. */
export function monthPeriod(month: string): Pick<Filters, 'dateFrom' | 'dateTo'> {
	const [year, number] = month.split('-').map(Number);
	const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
	return { dateFrom: `${month}-01`, dateTo: `${month}-${String(last).padStart(2, '0')}` };
}

/** A period that moves with the day: the quick picks of the filters, as a lens keeps them. */
export type RelativePeriod = 'this_year' | 'last_12_months' | 'last_year';
export const RELATIVE_PERIODS: readonly RelativePeriod[] = [
	'this_year',
	'last_12_months',
	'last_year'
];

/** An ISO day in the browser's time. */
export function isoDay(day: Date): string {
	return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
}

/** The days of `period` as of `today`: this or last year, or the twelve months up to today. */
export function relativePeriod(
	period: RelativePeriod,
	today: Date
): Pick<Filters, 'dateFrom' | 'dateTo'> {
	const year = today.getFullYear();
	switch (period) {
		case 'this_year':
			return yearPeriod(year);
		case 'last_year':
			return yearPeriod(year - 1);
		case 'last_12_months': {
			const start = new Date(year - 1, today.getMonth(), today.getDate() + 1);
			return { dateFrom: isoDay(start), dateTo: null };
		}
	}
}

/** Which relative period the period of the filters is as of `today`, if any. */
export function relativeOf(
	filters: Pick<Filters, 'dateFrom' | 'dateTo'>,
	today: Date
): RelativePeriod | null {
	return (
		RELATIVE_PERIODS.find((period) => {
			const days = relativePeriod(period, today);
			return days.dateFrom === filters.dateFrom && days.dateTo === filters.dateTo;
		}) ?? null
	);
}

/** What the period of the filters is: a whole year, a whole month, another span, or none. */
export type PeriodChoice =
	| { kind: 'year'; year: number }
	| { kind: 'month'; month: string }
	| { kind: 'span'; from: string | null; to: string | null }
	| null;

export function periodOf(filters: Pick<Filters, 'dateFrom' | 'dateTo'>): PeriodChoice {
	const { dateFrom: from, dateTo: to } = filters;
	if (!from && !to) return null;
	if (from && to) {
		const year = Number(from.slice(0, 4));
		const whole = yearPeriod(year);
		if (whole.dateFrom === from && whole.dateTo === to) return { kind: 'year', year };
		const month = monthPeriod(from.slice(0, 7));
		if (month.dateFrom === from && month.dateTo === to) {
			return { kind: 'month', month: from.slice(0, 7) };
		}
	}
	return { kind: 'span', from, to };
}

/** An ISO day, or null for anything else. */
function day(value: string | null): string | null {
	return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}
