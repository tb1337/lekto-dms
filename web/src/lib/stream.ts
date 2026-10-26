/**
 * The stream of documents (#145): lanes of a filter's documents, laid out on months. Pure
 * helpers for `StreamView`.
 */
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type StreamOut = components['schemas']['StreamOut'];
export type StreamLane = components['schemas']['StreamLaneOut'];
export type StreamDocument = components['schemas']['StreamDocumentOut'];

/** At most this many months on the axis: the newest. */
export const MAX_MONTHS = 36;

/** The day a document stands on: its date, else when it came in. */
export function dayOf(document: StreamDocument): string {
	return document.document_date ?? document.created_at.slice(0, 10);
}

/** `YYYY-MM` of an ISO day. */
export function monthOf(day: string): string {
	return day.slice(0, 7);
}

/** The months from the oldest to the newest day of the stream (expected dates included), at
 * most `MAX_MONTHS`, oldest first. */
export function monthsOf(stream: StreamOut): string[] {
	const days: string[] = [];
	for (const lane of stream.lanes) {
		days.push(...lane.documents.map(dayOf));
		if (lane.target) days.push(dayOf(lane.target));
		if (lane.expected) days.push(lane.expected.next_date);
	}
	if (days.length === 0) return [];
	const sorted = days.map(monthOf).sort();
	const months: string[] = [];
	let [year, month] = sorted[0].split('-').map(Number);
	const [lastYear, lastMonth] = sorted.at(-1)!.split('-').map(Number);
	while (year < lastYear || (year === lastYear && month <= lastMonth)) {
		months.push(`${year}-${String(month).padStart(2, '0')}`);
		month += 1;
		if (month > 12) [year, month] = [year + 1, 1];
	}
	return months.slice(-MAX_MONTHS);
}

/** What a lane is called: a series by its contact and type, a branch or chain by the type of
 * its first document, the rest "Einzeln". */
export function laneTitle(lane: StreamLane, lookup: Lookup | null): string {
	const typeName = (id: string | null | undefined) =>
		lookup?.documentTypes.find((entry) => entry.id === id)?.name ?? null;
	if (lane.kind === 'single') return m.stream_single();
	if (lane.kind === 'series') {
		const contact = lookup?.contacts.find((entry) => entry.id === lane.contact_id)?.name;
		return [contact, typeName(lane.document_type_id)].filter(Boolean).join(' · ');
	}
	return typeName(lane.documents[0]?.document_type_id) ?? m.stream_related();
}

/** The documents of a lane in one month, oldest first. */
export function inMonth(lane: StreamLane, month: string): StreamDocument[] {
	return lane.documents.filter((document) => monthOf(dayOf(document)) === month);
}
