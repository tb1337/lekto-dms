/**
 * What a step's details draw, read from its entry in the log (Tobi, 23.10.2026): for the text
 * recognition how well each page was read and what came of the file, the page images, the
 * characters of each page, the classifier's classes as bars against its threshold, the similar
 * documents with their similarity, the names and identifiers in the text. The rest of a step's
 * details are the rows of `signalSummary`.
 */
import type { components } from '#lib/api/schema.ts';
import { PAGE_BREAK } from '#lib/facts.ts';
import { formatNumber } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import type { Node } from '#lib/pipeline.ts';
import {
	count,
	identifierText,
	list,
	named,
	namedContacts,
	object,
	percent,
	personWithStrength,
	rankedPairs,
	text
} from '#lib/signals.ts';
export { neighbourList, pageBars, type Neighbour, type PageBar } from '#lib/signals.ts';
import { own } from '#lib/utils.ts';

type LogEntry = components['schemas']['LogEntry'];
type Json = Record<string, unknown>;

/** The steps whose details are drawn here rather than as rows. */
const DRAWN: readonly Node[] = ['ocr', 'pages', 'parse', 'signal_classifier', 'signal_neighbours'];

const abstained = (entry: LogEntry) => text(object(entry.output).abstained) !== null;

/** Whether the details of an entry are drawn (`StepDetails`): not for a signal that abstained,
 * whose reason the rows tell. */
export function drawsDetails(entry: LogEntry): boolean {
	return DRAWN.includes(entry.node) && !abstained(entry);
}

/** Whether an entry's rows are what the text names (`FactRows`), not the summary's. */
export function drawsFacts(entry: LogEntry): boolean {
	return entry.node === 'signal_facts' && !abstained(entry);
}

const share = (value: unknown) => (typeof value === 'number' ? Math.min(1, Math.max(0, value)) : 0);

/** What the text recognition noted besides the reason: colours converted for PDF/A, another
 * OCR's text replaced, the vision model that read the pages. */
export function ocrNotes(output: Json): string[] {
	const vision = object(output.vision);
	const model = text(vision.model);
	const notes: string[] = [];
	if (output.pdfa === false) notes.push(m.details_not_pdfa());
	if (output.rgb === true) notes.push(m.details_rgb());
	if (output.read_again === true) notes.push(m.details_read_again());
	if (model) notes.push(m.details_vision({ model, calls: formatNumber(count(vision.calls)) }));
	return notes;
}

/** The characters on each page of a text whose pages stand apart by a form feed on a line of
 * its own (`/documents/{id}/text`). */
export function pageCharacters(value: string): number[] {
	return value.split(PAGE_BREAK).map((page) => page.length);
}

/** The kinds of classes the classifier ranks, as the verdict names its fields. */
export type RankKind = 'contacts' | 'document_types' | 'topics' | 'spaces';

const FIELD_KIND: Record<string, RankKind> = {
	contact: 'contacts',
	document_type: 'document_types',
	topic: 'topics',
	space: 'spaces'
};

/** The classifier's threshold for each kind, as the verdict's candidates carry it. */
export function classifierThresholds(
	verdict: LogEntry | undefined
): Partial<Record<RankKind, number>> {
	const found: Partial<Record<RankKind, number>> = {};
	for (const check of list(object(verdict?.output).fields).map(object)) {
		const kind = own(FIELD_KIND, String(check.field));
		if (!kind || found[kind] !== undefined) continue;
		for (const candidate of list(check.candidates).map(object)) {
			const source = list(candidate.sources)
				.map(object)
				.find((each) => each.signal === 'signal_classifier' && typeof each.threshold === 'number');
			if (source) {
				found[kind] = source.threshold as number;
				break;
			}
		}
	}
	return found;
}

export interface Rank {
	name: string;
	/** 0..1 */
	share: number;
	/** The share as people read it ("52 %"). */
	label: string;
}

export interface RankGroup {
	kind: RankKind;
	label: string;
	ranks: Rank[];
	/** From which share the classifier names a class, if the verdict tells it; 0..1. */
	threshold: number | null;
}

const RANK_LABELS: Record<RankKind, () => string> = {
	contacts: m.signal_contacts,
	document_types: m.signal_document_types,
	topics: m.signal_topics,
	spaces: m.signal_spaces
};

/** The classifier's best classes per kind (at most three each): contacts, types, and topics
 * and spaces where it was asked for them; each with its threshold where known. */
export function classifierRanks(
	output: Json,
	lookup: Lookup | null,
	thresholds: Partial<Record<RankKind, number>> = {}
): RankGroup[] {
	const kinds: RankKind[] = ['contacts', 'document_types'];
	if ('topics' in output) kinds.push('topics');
	if ('spaces' in output) kinds.push('spaces');
	return kinds.map((kind) => ({
		kind,
		label: RANK_LABELS[kind](),
		threshold: thresholds[kind] ?? null,
		ranks: rankedPairs(output[kind]).map(({ id, probability }) => ({
			name: named(id, lookup),
			share: share(probability),
			label: percent(probability)
		}))
	}));
}

export interface Facts {
	/** The contacts whose name or alias stands in the text. */
	named: string[];
	/** Identifiers of known contacts: "Personalnummer 20417 → Schwälmer Brotladen". */
	identifiers: string[];
	/** Identifiers no contact has. */
	unknown: string[];
	/** The persons the text names, with the strength of the evidence. */
	persons: string[];
}

/** What the facts signal found in the text. */
export function factsOf(output: Json, lookup: Lookup | null): Facts {
	return {
		named: namedContacts(output),
		identifiers: list(output.identifiers)
			.map(object)
			.map((found) => {
				const values = {
					identifier: identifierText(found),
					contact: named(found.contact_id, lookup)
				};
				return typeof found.topic_id === 'string'
					? m.details_identifier_topic({ ...values, topic: named(found.topic_id, lookup) })
					: m.details_identifier(values);
			}),
		unknown: list(output.unknown_identifiers).map((item) => identifierText(object(item))),
		persons: list(output.persons).map((item) => personWithStrength(item, lookup))
	};
}
