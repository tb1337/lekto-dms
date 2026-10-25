/**
 * One line per step of the processing view: what the step found, read from its entry in the
 * log, so the list of steps tells the run at a glance; the step's details tell the rest.
 */
import type { components } from '#lib/api/schema.ts';
import { describeValue, fieldLabel } from '#lib/describe.ts';
import { formatDate, formatNumber } from '#lib/i18n.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { labelled, outputReasonText, reasonsText } from '#lib/reasons.ts';
import type { Node, NodeState } from '#lib/pipeline.ts';
import {
	count,
	kind,
	list,
	named,
	namedContacts,
	object,
	percent,
	person,
	SIGNAL_NODES,
	text
} from '#lib/signals.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];
type Json = Record<string, unknown>;

const SEPARATOR = ' · ';

/** Whether a person wrote the entry (`person`, `person:<id>`) or it came with the source
 * system's metadata (`imported`), not the step itself. */
export function byPerson(entry: LogEntry): boolean {
	const version = entry.model_version ?? '';
	return version === 'imported' || version === 'person' || version.startsWith('person:');
}

/** A person's confirmation of a step that had not ended OK (the entry the inbox writes for a
 * step it overrules): who confirmed it and how the step had ended; null for any other entry. */
export function confirmationOf(
	entry: LogEntry
): { by: unknown; before: 'uncertain' | 'failed' } | null {
	if (entry.model_version !== 'person') return null;
	const output = object(entry.output);
	const before = output.outcome_before;
	return before === 'uncertain' || before === 'failed' ? { by: output.confirmed_by, before } : null;
}

/** Whether a step counts as OK although its last entry is uncertain: a later step of its run
 * settled it (the rules filed the document into the space the verdict suggested). */
export function settled(state: NodeState | null, entry: LogEntry): boolean {
	return state?.outcome === 'ok' && entry.outcome === 'uncertain' && !byPerson(entry);
}

/**
 * The line of a step: what its last entry in the run found; for a filing that waits for a
 * person (`status` review: the current run stopped for one) that it does, and for a step it
 * left uncertain that it is open; for a step a person or the rules overruled how it ended and
 * who settled it. Null while nothing is to tell: it did not run, waits, runs or was skipped.
 */
export function stepSummary(
	node: Node,
	state: NodeState | null,
	entry: LogEntry | undefined,
	status: ProcessingStatus,
	lookup: Lookup | null
): string | null {
	if (state?.status === 'waiting' && node === 'file' && status === 'review') {
		return m.summary_file_waits();
	}
	if (state?.status !== 'done' || !entry) return null;
	const confirmed = confirmationOf(entry);
	if (confirmed) {
		const name = person(confirmed.by, lookup);
		return confirmed.before === 'failed'
			? m.summary_overruled_decided({ name })
			: m.summary_overruled_confirmed({ name });
	}
	if (settled(state, entry)) return m.summary_overruled_settled();
	if (entry.outcome === 'failed') return reasonsText(entry.reasons, entry.reason, labelled(lookup));
	if (byPerson(entry)) {
		return entry.model_version === 'imported' ? m.summary_imported() : m.summary_person();
	}
	const output = object(entry.output);
	const abstained = outputReasonText(output.abstained_reason, output.abstained, labelled(lookup));
	if (abstained && (SIGNAL_NODES as readonly string[]).includes(node)) {
		return `${m.signal_abstained()}: ${abstained}`;
	}
	switch (node) {
		case 'receive':
			return formatDate(entry.started_at, { dateStyle: 'short', timeStyle: 'short' });
		case 'ocr':
			return recognised(output);
		case 'pages':
			return count(output.pages) === 1
				? m.summary_page_images_one()
				: m.summary_page_images({ count: formatNumber(count(output.pages)) });
		case 'parse':
			return m.summary_characters({ count: formatNumber(count(output.characters)) });
		case 'signal_llm':
			return proposed(object(output.proposal));
		case 'signal_classifier':
			return classified(output, lookup);
		case 'signal_neighbours':
			return alike(output, lookup);
		case 'signal_facts':
			return found(output, lookup);
		case 'judge':
			return judged(output, status === 'review', lookup);
		case 'fields':
			return read(output);
		case 'apply_rules':
			return ruled(entry, lookup);
		case 'file':
			return m.summary_filed();
		default:
			return null;
	}
}

function recognised(output: Json): string {
	const pages = count(output.pages);
	return [
		pages === 1 ? m.summary_pages_read_one() : m.summary_pages_read({ count: formatNumber(pages) }),
		output.vision ? m.summary_read_by_vision() : null,
		output.pdfa === true ? m.summary_pdfa() : m.summary_not_pdfa(),
		output.rgb === true ? m.summary_rgb() : null,
		output.read_again === true ? m.summary_read_again() : null
	]
		.filter(Boolean)
		.join(SEPARATOR);
}

function proposed(proposal: Json): string {
	const sender = text(object(proposal.sender).value);
	const recipient = text(proposal.recipient);
	const type = text(proposal.document_type);
	const created = text(proposal.new_document_type);
	const who =
		sender && recipient
			? m.summary_from_to({ sender, recipient })
			: (sender ?? (recipient ? m.summary_to({ recipient }) : null));
	const what = type ?? (created ? `${created} (${m.candidate_new()})` : null);
	const parts = [who, what].filter(Boolean);
	return parts.length > 0 ? parts.join(SEPARATOR) : m.summary_nothing();
}

/** "JUKO Marburg e.V. 52 % · Lohnabrechnung 91 %": the best contact and type. */
function classified(output: Json, lookup: Lookup | null): string {
	const best = (value: unknown) => {
		const [id, probability] = list(list(value)[0]);
		return id === undefined ? null : `${named(id, lookup)} ${percent(probability)}`;
	};
	const parts = [best(output.contacts), best(output.document_types)].filter(Boolean);
	return parts.length > 0 ? parts.join(SEPARATOR) : m.summary_nothing();
}

/** "5 Dokumente, 4 davon JUKO Marburg e.V.": how many similar documents, and the contact most
 * of them have. */
function alike(output: Json, lookup: Lookup | null): string {
	const neighbours = list(output.neighbours).map(object);
	const total = neighbours.length;
	if (total === 0) return m.summary_neighbours_none();
	const tally = new Map<string, number>();
	for (const neighbour of neighbours) {
		if (typeof neighbour.contact_id === 'string') {
			tally.set(neighbour.contact_id, (tally.get(neighbour.contact_id) ?? 0) + 1);
		}
	}
	const [contact, share] = [...tally].sort((a, b) => b[1] - a[1])[0] ?? [null, 0];
	const documents =
		total === 1 ? m.summary_neighbours_one() : m.summary_neighbours({ count: String(total) });
	if (contact === null || share < 2) return documents;
	const name = named(contact, lookup);
	return share === total
		? m.summary_neighbours_all({ documents, contact: name })
		: m.summary_neighbours_most({ documents, share: String(share), contact: name });
}

/** "Personalnummer gehört zu Schwälmer Brotladen · nennt Anna Leider": the first known
 * identifier, else the contacts named, and the persons. */
function found(output: Json, lookup: Lookup | null): string {
	const identifier = list(output.identifiers).map(object)[0];
	const names = namedContacts(output);
	const persons = list(output.persons).map((item) => person(object(item).user_id, lookup));
	const parts = [
		identifier
			? m.summary_identifier({
					kind: kind(identifier.kind),
					contact: named(identifier.contact_id, lookup)
				})
			: names.length > 0
				? m.summary_named({ names: names.join(', ') })
				: null,
		persons.length > 0 ? m.summary_named({ names: persons.join(', ') }) : null
	].filter(Boolean);
	return parts.length > 0 ? parts.join(SEPARATOR) : m.summary_facts_none();
}

/** The fields the verdict left uncertain (`open`: still waiting for a person) and who would not
 * see the document where it leads; when nothing is uncertain, the contact and type it decided. */
function judged(output: Json, open: boolean, lookup: Lookup | null): string {
	const checks = list(output.fields).map(object);
	const unsure = checks.filter(
		(check) => check.outcome === 'uncertain' || check.outcome === 'failed'
	);
	if (unsure.length > 0) {
		const fields = unsure.map((check) => fieldLabel(String(check.field), lookup)).join(', ');
		const unseen = list(checks.find((check) => check.field === 'space')?.unseen_by).map((id) =>
			person(id, lookup)
		);
		return [
			open ? m.summary_open({ fields }) : m.summary_unsure({ fields }),
			unseen.length === 1
				? m.summary_unseen_one({ name: unseen[0] })
				: unseen.length > 1
					? m.summary_unseen({ names: unseen.join(', ') })
					: null
		]
			.filter(Boolean)
			.join(SEPARATOR);
	}
	const decided = ['contact', 'document_type']
		.map((field) => checks.find((check) => check.field === field)?.value)
		.filter((value) => typeof value === 'string')
		.map((value) => describeValue(value, lookup));
	return decided.length > 0 ? decided.join(SEPARATOR) : m.summary_decided();
}

/** "6 Felder gelesen": the fields of the type the document shows a value for, of all of them
 * (the title the step checks too is none of them). */
function read(output: Json): string {
	const checks = list(output.fields)
		.map(object)
		.filter((check) => String(check.field).startsWith('field:'));
	if (checks.length === 0) return m.summary_fields_none();
	const found = checks.filter((check) => check.value !== null && check.value !== undefined).length;
	if (found === checks.length) {
		return found === 1
			? m.summary_fields_read_one()
			: m.summary_fields_read({ count: String(found) });
	}
	return m.summary_fields_partly({ read: String(found), count: String(checks.length) });
}

/** The spaces the document went through or the one whose rules ran when it arrived, and how
 * many of the rules looked at took effect; what stopped them instead, if anything did. */
function ruled(entry: LogEntry, lookup: Lookup | null): string {
	const output = object(entry.output);
	const input = object(entry.input);
	const problem = outputReasonText(output.problem_reason, output.problem, labelled(lookup));
	if (problem) return problem;
	const chain = list(output.spaces);
	const where =
		chain.length > 1
			? chain.map((id) => named(id, lookup)).join(' → ')
			: input.trigger === 'ingest' && typeof input.space_id === 'string'
				? m.summary_rules_arrived({ space: named(input.space_id, lookup) })
				: null;
	const looked = list(input.rules).length;
	const matched = list(output.rules).length;
	const took =
		looked === 0
			? m.summary_rules_absent()
			: matched === 0
				? m.summary_rules_none({ count: String(looked) })
				: matched === 1
					? m.summary_rules_matched_one({ count: String(looked) })
					: m.summary_rules_matched({ matched: String(matched), count: String(looked) });
	return [where, took].filter(Boolean).join(SEPARATOR);
}
