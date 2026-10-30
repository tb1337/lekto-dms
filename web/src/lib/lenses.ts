/**
 * Lenses: a user's saved looks at the documents. Opening one writes its filters and sort into
 * the URL of the documents (with `lens=<id>`), a fact's value by its reference; a relative
 * period becomes the days it means today. Its words go into the history entry, never into the
 * URL (`lib/words.ts`). Saving takes them from there again: a period that is one of the quick
 * picks today stays relative.
 */

import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';
import { rememberRef } from '#lib/fact-refs.svelte.ts';
import { factFilter, parseFactFilter } from '#lib/facts.ts';
import {
	apiQuery,
	relativeOf,
	relativePeriod,
	writeFilters,
	type Filters,
	type RelativePeriod
} from '#lib/filters.ts';

export type Lens = components['schemas']['LensOut'];
export type LensFilter = components['schemas']['LensFilterBody'];
/** The filters of a lens as it is read (each fact with its value) or as it is written. */
type AnyLensFilter = LensFilter | Lens['filter'];
export type LensSort = components['schemas']['LensSort'];
export type Grouping = components['schemas']['Grouping'];

/** The filters a lens keeps, as of `today` (a moving period as its days). */
export function filtersOf(filter: AnyLensFilter, today: Date): Filters {
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
		...period,
		facts: (filter.facts ?? []).map((fact) =>
			factFilter(fact.kind ?? null, fact.ref ?? null, fact.role ?? null)
		)
	};
}

/** The filters of `lens` as of `today`. */
export function lensFilters(lens: Lens, today: Date): Filters {
	return filtersOf(lens.filter, today);
}

/** The values of the facts of `lenses`, for the labels of the filter (`fact-refs`). */
export function rememberLensFacts(lenses: readonly Lens[]): void {
	for (const fact of lenses.flatMap((lens) => lens.filter.facts ?? [])) {
		if (fact.kind && fact.ref && fact.value) rememberRef(fact.kind, fact.ref, fact.value);
	}
}

/** The query of the documents page that opens `lens` as of `today`; its words go with it into
 * the history entry (`lens.query`). */
export function lensParams(lens: Lens, today: Date): URLSearchParams {
	const params = writeFilters(new URLSearchParams({ lens: lens.id }), lensFilters(lens, today));
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
		document_period: relative,
		facts: filters.facts.map((fact) => {
			const { kind, ref, role } = parseFactFilter(fact);
			return { kind, ref, role };
		})
	};
}

/** Whether the page (`params`, `words`) shows other filters, words or another sort than `lens`
 * as of `today`; the order of repeated values does not count. */
export function lensDiffers(
	lens: Lens,
	params: URLSearchParams,
	words: string,
	today: Date
): boolean {
	if (words !== (lens.query ?? '')) return true;
	const wanted = lensParams(lens, today);
	const keys = new Set([...wanted.keys(), ...params.keys()]);
	keys.delete('lens');
	const values = (from: URLSearchParams, key: string) => from.getAll(key).toSorted().join('\n');
	return [...keys].some((key) => values(wanted, key) !== values(params, key));
}

/** How many documents a lens shows today (null: all documents): with words, as the search by
 * words alone estimates them (no embedding for a count); else as the filters count them. */
export async function lensCount(
	lens: Lens | null,
	today: Date,
	allUsers: boolean
): Promise<number> {
	const query = lens
		? apiQuery(lensFilters(lens, today), allUsers)
		: { all_users: allUsers || undefined };
	if (lens?.query) {
		const found = await unwrap(
			api.POST('/api/v1/documents/search', {
				params: { query: { ...query, limit: 1, semantic_ratio: 0 } },
				body: { q: lens.query }
			})
		);
		return found.estimated_total;
	}
	const counted = await unwrap(api.GET('/api/v1/documents/count', { params: { query } }));
	return counted.total;
}
