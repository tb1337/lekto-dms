/**
 * Lenses: a user's saved looks at the documents. Opening one writes its filters, words and
 * sort into the URL of the documents (with `lens=<id>`); a relative period becomes the days it
 * means today. Saving takes them from the URL again: a period that is one of the quick picks
 * today stays relative.
 */

import type { components } from '#lib/api/schema.ts';
import {
	relativeOf,
	relativePeriod,
	writeFilters,
	type Filters,
	type RelativePeriod
} from '#lib/filters.ts';

export type Lens = components['schemas']['LensOut'];
export type LensFilter = components['schemas']['LensFilterBody'];
export type LensSort = components['schemas']['LensSort'];
export type Grouping = components['schemas']['Grouping'];

/** The filters a lens keeps, as of `today` (a moving period as its days). */
export function filtersOf(filter: LensFilter, today: Date): Filters {
	const period = filter.document_period
		? relativePeriod(filter.document_period, today)
		: { dateFrom: filter.document_date_from ?? null, dateTo: filter.document_date_to ?? null };
	return {
		contacts: filter.contact_ids ?? [],
		types: filter.document_type_ids ?? [],
		tags: filter.tag_ids ?? [],
		contactGroups: filter.contact_group_ids ?? [],
		typeGroups: filter.document_type_group_ids ?? [],
		topics: filter.topic_ids ?? [],
		spaces: filter.space_ids ?? [],
		field: filter.field_id ?? null,
		...period
	};
}

/** The filters of `lens` as of `today`. */
export function lensFilters(lens: Lens, today: Date): Filters {
	return filtersOf(lens.filter, today);
}

/** The query of the documents page that opens `lens` as of `today`. */
export function lensParams(lens: Lens, today: Date): URLSearchParams {
	const params = writeFilters(new URLSearchParams({ lens: lens.id }), lensFilters(lens, today));
	if (lens.query) params.set('q', lens.query);
	if (lens.sort) params.set('sort', lens.sort);
	if (lens.sort_field_id) params.set('sort_field', lens.sort_field_id);
	return params;
}

/** `filters` as a lens keeps them: a quick pick of today as that, other periods as days. */
export function lensFilter(filters: Filters, today: Date): LensFilter {
	const relative: RelativePeriod | null = relativeOf(filters, today);
	return {
		contact_ids: filters.contacts,
		document_type_ids: filters.types,
		tag_ids: filters.tags,
		contact_group_ids: filters.contactGroups,
		document_type_group_ids: filters.typeGroups,
		topic_ids: filters.topics,
		space_ids: filters.spaces,
		field_id: filters.field,
		document_date_from: relative ? null : filters.dateFrom,
		document_date_to: relative ? null : filters.dateTo,
		document_period: relative
	};
}

/** Whether the page (`params`) shows other filters, words or another sort than `lens` as of
 * `today`; the order of repeated values does not count. */
export function lensDiffers(lens: Lens, params: URLSearchParams, today: Date): boolean {
	const wanted = lensParams(lens, today);
	const keys = new Set([...wanted.keys(), ...params.keys()]);
	keys.delete('lens');
	const values = (from: URLSearchParams, key: string) => from.getAll(key).toSorted().join('\n');
	return [...keys].some((key) => values(wanted, key) !== values(params, key));
}
