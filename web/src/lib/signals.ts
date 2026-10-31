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
import { formatNumber, formatPercent } from '#lib/i18n.ts';
import { labelOfKind, printed } from '#lib/identifiers.ts';
import type { Strength } from '#lib/facts.ts';
import { userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { labelled, outputReasonText } from '#lib/reasons.ts';
import { own } from '#lib/utils.ts';

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
export const percent = (value: unknown) => formatPercent(typeof value === 'number' ? value : 0);
export const count = (value: unknown) => (typeof value === 'number' ? value : 0);

export const kind = (value: unknown): string => labelOfKind(String(value));

/** `kind value` of an identifier the text names: "Personalnummer 20417". */
export function identifierText(found: Json): string {
	return `${kind(found.kind)} ${printed(String(found.kind ?? ''), String(found.value ?? ''))}`;
}

/** The contacts the facts signal found by name or alias. */
export function namedContacts(output: Json): string[] {
	return list(output.named)
		.map((item) => text(object(item).name))
		.filter((name): name is string => name !== null);
}

/** The classes a signal ranks, as `[id, probability]` pairs in the log, the first `count`. */
export function rankedPairs(value: unknown, count = 3): { id: unknown; probability: unknown }[] {
	return list(value)
		.slice(0, count)
		.map((pair) => {
			const [id, probability] = list(pair);
			return { id, probability };
		});
}

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

export interface Neighbour {
	title: string;
	/** The document, where the caller reads it. */
	id: string | null;
	href: string | null;
	/** Contact, type, topic and space of the document, by name. */
	parts: string[];
	/** The same in one line. */
	about: string;
	/** 0..1; null if the entry has none. */
	similarity: number | null;
	/** The similarity with two decimals; null if the entry has none. */
	label: string | null;
}

/** The similar documents, the most similar first, as the signal found them. */
export function neighbourList(output: Json, lookup: Lookup | null): Neighbour[] {
	return list(output.neighbours).map((item, index) => {
		const found = object(item);
		const score = typeof found.score === 'number' ? found.score : null;
		const parts = [found.contact_id, found.document_type_id, found.topic_id, found.space_id]
			.filter((id) => typeof id === 'string')
			.map((id) => named(id, lookup));
		return {
			title: m.signal_document({ number: index + 1 }),
			id: typeof found.document_id === 'string' ? found.document_id : null,
			href: typeof found.document_id === 'string' ? documentHref(found.document_id) : null,
			parts,
			about: parts.join(' · '),
			similarity: score === null ? null : Math.min(1, Math.max(0, score)),
			label:
				score === null
					? null
					: formatNumber(score, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
		};
	});
}

export function named(id: unknown, lookup: Lookup | null): string {
	return typeof id === 'string' ? describeValue(id, lookup) : m.value_unset();
}

/** Ranked classes as `[id, probability]` pairs, at most `count`. */
function ranked(value: unknown, lookup: Lookup | null, count = 3): SummaryItem[] {
	return rankedPairs(value, count).map(({ id, probability }) => ({
		text: `${named(id, lookup)} ${percent(probability)}`
	}));
}

const WITH_STRENGTH: Record<Strength, (inputs: { name: string }) => string> = {
	hard: m.signal_person_hard,
	medium: m.signal_person_medium,
	weak: m.signal_person_weak
};

/** A person an entry names, with the strength of the evidence in brackets: "Anna Leider
 * (sicher belegt)". */
export function personWithStrength(item: unknown, lookup: Lookup | null): string {
	const found = object(item);
	const name = person(found.user_id, lookup);
	const strength = String(found.strength ?? '');
	return Object.hasOwn(WITH_STRENGTH, strength)
		? WITH_STRENGTH[strength as Strength]({ name })
		: name;
}

/** The persons an entry names, by name, with the strength of the evidence. */
function persons(value: unknown, lookup: Lookup | null): SummaryItem[] {
	return list(value).map((item) => ({ text: personWithStrength(item, lookup) }));
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
	const items = pageBars(output).map(({ text }) => ({ text }));
	return items.length === 0 ? [] : [{ label: m.log_reading(), items }];
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
					: (own(LABEL_TEXTS, outcome) ?? m.log_label_unknown)({ label });
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
	const problem = outputReasonText(output.problem_reason, output.problem, labelled(lookup));
	if (problem) rows.push({ label: m.log_rules_problem(), items: [{ text: problem }] });
	rows.push(...ruleSteps(output, lookup));
	return rows;
}

/** The steps of the rules that ask or check between their actions: a row per rule, an item
 * per step. */
function ruleSteps(output: Json, lookup: Lookup | null): SummaryRow[] {
	const names = new Map(
		list(output.rules)
			.map(object)
			.map((report) => [text(report.rule_id), text(report.name)] as const)
	);
	return list(output.steps)
		.map(object)
		.map((logged) => ({
			label: m.log_rules_steps({ rule: names.get(text(logged.rule_id)) ?? m.rule_unknown() }),
			items: list(logged.steps)
				.map(object)
				.map((step) => ({ text: stepText(step, lookup) }))
		}));
}

const MAX_ANSWER_SHOWN = 200;

function stepText(step: Json, lookup: Lookup | null): string {
	if (step.type === 'condition') return step.holds ? m.log_step_holds() : m.log_step_fails();
	const name = text(step.name) ?? '';
	const reason = outputReasonText(step.reason, null, labelled(lookup)) ?? '';
	if (step.status === 'answered') {
		const shown = step.answer_too_long
			? m.log_step_answer_long()
			: JSON.stringify(step.answer ?? null).slice(0, MAX_ANSWER_SHOWN);
		const producer = text(step.producer);
		return producer
			? m.log_step_answered_by({ name, producer, answer: shown })
			: m.log_step_answered({ name, answer: shown });
	}
	if (step.status === 'open' || step.status === 'queued') return m.log_step_waiting({ name });
	if (step.status === 'asking') return m.log_step_asking({ name });
	if (step.status === 'not_asked') return m.log_step_not_asked({ name });
	return step.reported
		? m.log_step_reported({ name, reason })
		: m.log_step_no_answer({ name, reason });
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
	const abstained = outputReasonText(output.abstained_reason, output.abstained, labelled(lookup));
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
					neighbourList(output, lookup).map(({ title, parts, label, href }) => {
						const said = parts.length > 0 ? `${title}: ${parts.join(', ')}` : title;
						const alike = label === null ? null : m.signal_similarity({ similarity: label });
						return { text: alike ? `${said} · ${alike}` : said, href: href ?? undefined };
					})
				)
			];
		case 'signal_facts':
			return [
				row(
					m.signal_named(),
					namedContacts(output).map((name) => ({ text: name }))
				),
				row(
					m.signal_identifiers(),
					list(output.identifiers).map((item) => {
						const found = object(item);
						const topic =
							typeof found.topic_id === 'string' ? ` · ${named(found.topic_id, lookup)}` : '';
						return {
							text: `${identifierText(found)}: ${named(found.contact_id, lookup)}${topic}`
						};
					})
				),
				row(
					m.signal_unknown_identifiers(),
					list(output.unknown_identifiers).map((item) => ({ text: identifierText(object(item)) }))
				),
				...('persons' in output ? [row(m.facts_persons(), persons(output.persons, lookup))] : [])
			];
		default:
			return [];
	}
}
