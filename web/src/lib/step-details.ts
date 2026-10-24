/**
 * What a step's details draw, read from its entry in the log (Tobi, 23.10.2026): for the text
 * recognition how well each page was read and what came of the file, the page images, the
 * characters of each page, the classifier's classes as bars against its threshold, the similar
 * documents with their similarity, the names and identifiers in the text. The rest of a step's
 * details are the rows of `signalSummary`.
 */
import type { components } from '#lib/api/schema.ts';
import { documentHref } from '#lib/candidates.ts';
import { formatNumber } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import type { Node } from '#lib/pipeline.ts';
import { kind, list, named, object, percent, personWithStrength, text } from '#lib/signals.ts';
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
const count = (value: unknown) => (typeof value === 'number' ? value : 0);

export interface PageBar {
	page: number;
	words: number;
	/** The share of unsure words, 0..1. */
	unsure: number;
	label: string;
	/** The log's line for the page: unsure words of all, and of the content where counted. */
	text: string;
}

/** How well the OCR read each page it recognised; none where pages had text of their own. */
export function pageBars(output: Json): PageBar[] {
	return list(output.readings)
		.map(object)
		.map((page) => {
			const words = count(page.words);
			const unsure = words > 0 ? count(page.unsure) / words : 0;
			const content = typeof page.content === 'number' ? page.content : null;
			const values = {
				page: String(page.page),
				unsure: percent(unsure),
				words: formatNumber(words)
			};
			return {
				page: count(page.page),
				words,
				unsure,
				label: percent(unsure),
				text:
					content === null
						? m.log_reading_page(values)
						: m.log_reading_page_content({
								...values,
								content_unsure: percent(content > 0 ? count(page.content_unsure) / content : 0),
								content: formatNumber(content)
							})
			};
		});
}

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
	return value.split(/\n?\f\n?/).map((page) => page.length);
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
		ranks: list(output[kind])
			.slice(0, 3)
			.map((pair) => {
				const [id, probability] = list(pair);
				return { name: named(id, lookup), share: share(probability), label: percent(probability) };
			})
	}));
}

export interface Neighbour {
	title: string;
	href: string | null;
	/** Contact, type, topic and space of the document, by name. */
	about: string;
	/** 0..1; null if the entry has none. */
	similarity: number | null;
	label: string | null;
}

/** The similar documents, the most similar first, as the signal found them. */
export function neighbourList(output: Json, lookup: Lookup | null): Neighbour[] {
	return list(output.neighbours).map((item, index) => {
		const found = object(item);
		const score = typeof found.score === 'number' ? found.score : null;
		return {
			title: m.signal_document({ number: index + 1 }),
			href: typeof found.document_id === 'string' ? documentHref(found.document_id) : null,
			about: [found.contact_id, found.document_type_id, found.topic_id, found.space_id]
				.filter((id) => typeof id === 'string')
				.map((id) => named(id, lookup))
				.join(' · '),
			similarity: score === null ? null : share(score),
			label:
				score === null
					? null
					: formatNumber(score, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
		};
	});
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
	const identifier = (found: Json) => `${kind(found.kind)} ${String(found.value ?? '')}`;
	return {
		named: list(output.named)
			.map((item) => text(object(item).name))
			.filter((name): name is string => name !== null),
		identifiers: list(output.identifiers)
			.map(object)
			.map((found) => {
				const values = { identifier: identifier(found), contact: named(found.contact_id, lookup) };
				return typeof found.topic_id === 'string'
					? m.details_identifier_topic({ ...values, topic: named(found.topic_id, lookup) })
					: m.details_identifier(values);
			}),
		unknown: list(output.unknown_identifiers).map((item) => identifier(object(item))),
		persons: list(output.persons).map((item) => personWithStrength(item, lookup))
	};
}
