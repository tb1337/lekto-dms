/**
 * What a signal said in a run, for the protocol: the language model's proposal, the
 * classifier's best classes, the similar documents, the names and identifiers in the text, or
 * why it abstained. For the OCR, how well it read each page it recognised; for the fields node,
 * whether each value stands by its label; for the rules, the spaces a document went through and
 * the space whose rules ran when it arrived there.
 */
import type { components } from '#lib/api/schema.ts';
import { documentHref } from '#lib/candidates.ts';
import { describeValue, fieldLabel } from '#lib/describe.ts';
import { formatNumber } from '#lib/i18n.ts';
import { IDENTIFIER_KINDS, kindLabel, type IdentifierKind } from '#lib/identifiers.ts';
import { strengthLabel, type Strength } from '#lib/facts.ts';
import { userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

type LogEntry = components['schemas']['LogEntry'];

export const SIGNAL_NODES = [
	'signal_llm',
	'signal_classifier',
	'signal_neighbours',
	'signal_facts'
] as const;

export interface SummaryItem {
	text: string;
	href?: string;
}

export interface SummaryRow {
	label: string;
	items: SummaryItem[];
}

type Json = Record<string, unknown>;

export const object = (value: unknown): Json =>
	value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {};
export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
export const text = (value: unknown): string | null =>
	typeof value === 'string' && value.trim() !== '' ? value : null;
export const percent = (value: unknown) =>
	formatNumber(typeof value === 'number' ? value : 0, {
		style: 'percent',
		maximumFractionDigits: 0
	});

export function kind(value: unknown): string {
	const name = String(value);
	return (IDENTIFIER_KINDS as readonly string[]).includes(name)
		? kindLabel(name as IdentifierKind)
		: name;
}

export function named(id: unknown, lookup: Lookup | null): string {
	return typeof id === 'string' ? describeValue(id, lookup) : m.value_unset();
}

/** Ranked classes as `[id, probability]` pairs, at most `count`. */
function ranked(value: unknown, lookup: Lookup | null, count = 3): SummaryItem[] {
	return list(value)
		.slice(0, count)
		.map((pair) => {
			const [id, probability] = list(pair);
			return { text: `${named(id, lookup)} ${percent(probability)}` };
		});
}

/** The persons an entry names, by name, with the strength of the evidence. */
function persons(value: unknown, lookup: Lookup | null): SummaryItem[] {
	return list(value).map((item) => {
		const found = object(item);
		const strength = String(found.strength ?? '');
		const label = ['hard', 'medium', 'weak'].includes(strength)
			? strengthLabel(strength as Strength)
			: strength;
		return { text: `${person(found.user_id, lookup)} · ${label}` };
	});
}

export function person(id: unknown, lookup: Lookup | null): string {
	const user = lookup?.users.find((entry) => entry.id === id);
	return user ? userLabel(user) : m.space_named_someone();
}

/** The judge's entry: the persons it weighed for the space, and those of them who would not
 * see the document where the space check leads. None without a space check. */
function judged(output: Json, lookup: Lookup | null): SummaryRow[] {
	const space = list(output.fields)
		.map(object)
		.find((check) => check.field === 'space');
	if (!space) return [];
	const rows: SummaryRow[] = [];
	if ('persons' in output) rows.push(row(m.facts_persons(), persons(output.persons, lookup)));
	const unseen = list(space.unseen_by);
	if (unseen.length > 0)
		rows.push(
			row(
				m.log_space_unseen(),
				unseen.map((id) => ({ text: person(id, lookup) }))
			)
		);
	return rows;
}

function row(label: string, items: SummaryItem[]): SummaryRow {
	return { label, items: items.length > 0 ? items : [{ text: m.signal_none() }] };
}

/** How well the OCR read each page it recognised, of all words and of the content where it
 * was counted; none where pages had text of their own. */
function readings(output: Json): SummaryRow[] {
	const pages = list(output.readings).map(object);
	if (pages.length === 0) return [];
	const count = (value: unknown) => (typeof value === 'number' ? value : 0);
	const items = pages.map((page) => {
		const words = count(page.words);
		const share = percent(words > 0 ? count(page.unsure) / words : 0);
		if (typeof page.content !== 'number') {
			return {
				text: m.log_reading_page({
					page: String(page.page),
					unsure: share,
					words: formatNumber(words)
				})
			};
		}
		const content = page.content;
		return {
			text: m.log_reading_page_content({
				page: String(page.page),
				unsure: share,
				words: formatNumber(words),
				content_unsure: percent(content > 0 ? count(page.content_unsure) / content : 0),
				content: formatNumber(content)
			})
		};
	});
	return [{ label: m.log_reading(), items }];
}

const LABEL_TEXTS: Record<string, (inputs: { label: string }) => string> = {
	beside: m.log_label_beside,
	apart: m.log_label_apart,
	label_missing: m.log_label_missing,
	unknown: m.log_label_unknown
};

/** The label the model gave for each value the fields node read, and whether the value stands
 * by it; only recorded, so without a colour. None for checks without one. */
function labels(output: Json, lookup: Lookup | null): SummaryRow[] {
	return list(output.fields)
		.map(object)
		.flatMap((check) => {
			const found = object(check.label);
			const outcome = text(found.outcome);
			if (outcome === null) return [];
			const label = text(found.text);
			const said =
				label === null || outcome === 'no_label'
					? m.log_label_none()
					: (LABEL_TEXTS[outcome] ?? m.log_label_unknown)({ label });
			return [{ label: fieldLabel(String(check.field), lookup), items: [{ text: said }] }];
		});
}

/** The rules' entry: the spaces the document went through, one after another (the rules of
 * each filed it into the next), and for the rules of a space it arrived in, that space and what
 * stopped them (rules moving it back and forth). */
function rules(entry: LogEntry, lookup: Lookup | null): SummaryRow[] {
	const output = object(entry.output);
	const input = object(entry.input);
	const rows: SummaryRow[] = [];
	const chain = list(output.spaces);
	if (chain.length > 1) {
		rows.push({
			label: m.log_rules_chain(),
			items: [{ text: chain.map((id) => named(id, lookup)).join(' → ') }]
		});
	}
	if (input.trigger === 'ingest' && typeof input.space_id === 'string') {
		rows.push({ label: m.log_rules_arrived(), items: [{ text: named(input.space_id, lookup) }] });
	}
	const problem = text(output.problem);
	if (problem) rows.push({ label: m.log_rules_problem(), items: [{ text: problem }] });
	return rows;
}

/** The rows of a signal's entry, of the OCR's, or the labels of the fields node's; none for
 * other nodes. */
export function signalSummary(entry: LogEntry, lookup: Lookup | null): SummaryRow[] {
	if (entry.node === 'ocr') return readings(object(entry.output));
	if (entry.node === 'judge') return judged(object(entry.output), lookup);
	if (entry.node === 'fields') return labels(object(entry.output), lookup);
	if (entry.node === 'apply_rules') return rules(entry, lookup);
	if (!(SIGNAL_NODES as readonly string[]).includes(entry.node)) return [];
	const output = object(entry.output);
	const abstained = text(output.abstained);
	if (abstained) return [{ label: m.signal_abstained(), items: [{ text: abstained }] }];
	switch (entry.node) {
		case 'signal_llm': {
			const proposal = object(output.proposal);
			const value = (key: string, inner = false) => {
				const found = text(inner ? object(proposal[key]).value : proposal[key]);
				return found ? [{ text: found }] : [];
			};
			return [
				row(m.signal_sender(), value('sender', true)),
				row(m.signal_recipient(), value('recipient')),
				row(m.field_document_type(), [
					...value('document_type'),
					...value('new_document_type').map((item) => ({
						text: `${item.text} (${m.candidate_new()})`
					}))
				]),
				...('topic' in proposal ? [row(m.field_topic(), value('topic'))] : []),
				...(typeof proposal.space === 'string'
					? [row(m.field_space(), [{ text: named(proposal.space, lookup) }])]
					: []),
				row(m.field_date(), value('document_date', true)),
				row(m.field_title(), value('title')),
				row(m.signal_language(), value('language'))
			];
		}
		case 'signal_classifier':
			return [
				row(m.signal_contacts(), ranked(output.contacts, lookup)),
				row(m.signal_document_types(), ranked(output.document_types, lookup)),
				...('topics' in output ? [row(m.signal_topics(), ranked(output.topics, lookup))] : []),
				...('spaces' in output ? [row(m.signal_spaces(), ranked(output.spaces, lookup))] : [])
			];
		case 'signal_neighbours':
			return [
				row(
					m.signal_neighbours(),
					list(output.neighbours).map((item, index) => {
						const found = object(item);
						const about = [found.contact_id, found.document_type_id, found.topic_id, found.space_id]
							.filter((id) => typeof id === 'string')
							.map((id) => named(id, lookup));
						const title = m.signal_document({ number: index + 1 });
						const said = about.length > 0 ? `${title}: ${about.join(', ')}` : title;
						const alike =
							typeof found.score === 'number'
								? m.signal_similarity({
										similarity: formatNumber(found.score, {
											minimumFractionDigits: 2,
											maximumFractionDigits: 2
										})
									})
								: null;
						return {
							text: alike ? `${said} · ${alike}` : said,
							href:
								typeof found.document_id === 'string' ? documentHref(found.document_id) : undefined
						};
					})
				)
			];
		case 'signal_facts':
			return [
				row(
					m.signal_named(),
					list(output.named).map((item) => ({ text: String(object(item).name ?? '') }))
				),
				row(
					m.signal_identifiers(),
					list(output.identifiers).map((item) => {
						const found = object(item);
						const topic =
							typeof found.topic_id === 'string' ? ` · ${named(found.topic_id, lookup)}` : '';
						return {
							text: `${kind(found.kind)} ${String(found.value ?? '')}: ${named(found.contact_id, lookup)}${topic}`
						};
					})
				),
				row(
					m.signal_unknown_identifiers(),
					list(output.unknown_identifiers).map((item) => {
						const found = object(item);
						return { text: `${kind(found.kind)} ${String(found.value ?? '')}` };
					})
				),
				...('persons' in output ? [row(m.facts_persons(), persons(output.persons, lookup))] : [])
			];
		default:
			return [];
	}
}
