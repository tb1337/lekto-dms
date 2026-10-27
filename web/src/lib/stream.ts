/**
 * The stream of documents (#145): lanes of a filter's documents, laid out on months. Pure
 * helpers for `StreamView`.
 */
import type { components } from '#lib/api/schema.ts';
import { formatDate } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type StreamOut = components['schemas']['StreamOut'];
export type StreamLane = components['schemas']['StreamLaneOut'];
export type StreamDocument = components['schemas']['StreamDocumentOut'];

/** A column of the axis: a month, or a gap for a stretch of months without documents. */
export type AxisColumn =
	{ kind: 'month'; month: string } | { kind: 'gap'; months: number; from: string; to: string };

/** A stretch of this many months without documents folds into one gap column. */
export const GAP_FROM = 3;

/** The day a document stands on: its date, else when it came in. */
export function dayOf(document: StreamDocument): string {
	return document.document_date ?? document.created_at.slice(0, 10);
}

/** `YYYY-MM` of an ISO day. */
export function monthOf(day: string): string {
	return day.slice(0, 7);
}

/** The month after `month` (`YYYY-MM`). */
function nextMonth(month: string): string {
	let [year, number] = month.split('-').map(Number);
	number += 1;
	if (number > 12) [year, number] = [year + 1, 1];
	return `${year}-${String(number).padStart(2, '0')}`;
}

/** The months a stream stands on: of its documents, targets and expected dates. */
function occupiedMonths(stream: StreamOut): Set<string> {
	const months = new Set<string>();
	for (const lane of stream.lanes) {
		for (const document of lane.documents) months.add(monthOf(dayOf(document)));
		if (lane.target) months.add(monthOf(dayOf(lane.target)));
		if (lane.expected) months.add(monthOf(lane.expected.next_date));
	}
	return months;
}

/** The axis from the oldest to the newest month of the stream (expected dates included),
 * oldest first; a stretch of `GAP_FROM` or more months without documents is one gap column,
 * so the contract at the start of a lane stays in sight however old it is. */
export function axisOf(stream: StreamOut): AxisColumn[] {
	const occupied = occupiedMonths(stream);
	if (occupied.size === 0) return [];
	const sorted = [...occupied].sort();
	const last = sorted.at(-1)!;
	const columns: AxisColumn[] = [];
	let empty: string[] = [];
	const flush = () => {
		if (empty.length >= GAP_FROM) {
			columns.push({ kind: 'gap', months: empty.length, from: empty[0], to: empty.at(-1)! });
		} else {
			for (const month of empty) columns.push({ kind: 'month', month });
		}
		empty = [];
	};
	for (let month = sorted[0]; month <= last; month = nextMonth(month)) {
		if (occupied.has(month)) {
			flush();
			columns.push({ kind: 'month', month });
		} else {
			empty.push(month);
		}
	}
	return columns;
}

/** The month the grid shows at its right edge when it opens: that of the newest document (or
 * target), or today's when that is later; never an expected date far ahead. The last month
 * column of the axis up to it, where that month is no column (in a gap); null for an empty
 * stream. */
export function openingMonth(stream: StreamOut, axis: AxisColumn[], today: string): string | null {
	let newest = '';
	for (const lane of stream.lanes) {
		for (const document of lane.documents) {
			newest = newest > monthOf(dayOf(document)) ? newest : monthOf(dayOf(document));
		}
		if (lane.target) {
			newest = newest > monthOf(dayOf(lane.target)) ? newest : monthOf(dayOf(lane.target));
		}
	}
	const wanted = today.slice(0, 7) > newest ? today.slice(0, 7) : newest;
	let found: string | null = null;
	for (const column of axis) {
		if (column.kind === 'month' && column.month <= wanted) found = column.month;
	}
	return found;
}

/** What a lane is called: a series by its contact and type (its first document or number
 * while the names are not at hand), a branch or chain by the type and month of its first
 * document ("Reklamation · Aug. 26"; its title without a type), the rest "Einzeln". */
export function laneTitle(lane: StreamLane, lookup: Lookup | null): string {
	const typeName = (id: string | null | undefined) =>
		lookup?.documentTypes.find((entry) => entry.id === id)?.name ?? null;
	if (lane.kind === 'single') return m.stream_single();
	const first = lane.documents[0];
	if (lane.kind === 'series') {
		const contact = lookup?.contacts.find((entry) => entry.id === lane.contact_id)?.name;
		const named = [contact, typeName(lane.document_type_id)].filter(Boolean).join(' · ');
		return named || first?.title || lane.number || '';
	}
	if (!first) return m.stream_related();
	const name = typeName(first.document_type_id) ?? first.title;
	return `${name} · ${formatDate(dayOf(first), { month: 'short', year: '2-digit' })}`;
}

/** The documents of a lane in one month, oldest first. */
export function inMonth(lane: StreamLane, month: string): StreamDocument[] {
	return lane.documents.filter((document) => monthOf(dayOf(document)) === month);
}
