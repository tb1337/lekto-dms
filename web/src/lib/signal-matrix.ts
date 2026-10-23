/**
 * "Wer hat was erkannt?": for each property the verdict weighed (contact, type, topic, space),
 * what each of the four signals said about the value it decided or suggests, read from the
 * candidates of the verdict's checks. Its value is decided or open; a signal names it, proves
 * it by the text, suggests it (while it is open), names another value (against it, or without
 * evidence that would count), or is silent.
 */
import type { components } from '#lib/api/schema.ts';
import { sourceChips, type CandidateSource } from '#lib/candidates.ts';
import { describeValue, fieldLabel } from '#lib/describe.ts';
import { choiceTitle, filingKind, type Viewer } from '#lib/filing.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { NODE_LABELS } from '#lib/node-labels.ts';
import { m } from '#lib/paraglide/messages.js';
import { list, object, SIGNAL_NODES, text } from '#lib/signals.ts';

type LogEntry = components['schemas']['LogEntry'];
type Json = Record<string, unknown>;
export type Signal = (typeof SIGNAL_NODES)[number];

/** What a signal said about a property's value. */
export type CellKind = 'names' | 'evidence' | 'other' | 'contradicts' | 'silent';

export interface MatrixCell {
	signal: Signal;
	kind: CellKind;
	/** What it said, for the tooltip. */
	title: string;
}

export interface MatrixRow {
	field: string;
	label: string;
	/** The value decided, or the one suggested. */
	value: string;
	/** Decided (green), or open: a person decides (the cells that name it then suggest). */
	open: boolean;
	cells: MatrixCell[];
	/** The row in a word, for narrow screens: what made it green, or that it is open. */
	chip: string;
}

/** The properties the matrix shows, in its order; tags are left out. */
const FIELDS = ['contact', 'document_type', 'topic', 'space'] as const;

interface Candidate {
	value: unknown;
	label: string;
	sources: CandidateSource[];
	contradicted: boolean;
}

function candidatesOf(check: Json): Candidate[] {
	return list(check.candidates)
		.map(object)
		.map((item) => ({
			value: item.value ?? null,
			label: text(item.label) ?? '',
			// The log keeps the count of similar documents as `of`, the API names it `found`.
			sources: list(item.sources)
				.map(object)
				.map((source) => ({ ...source, found: source.found ?? source.of }) as CandidateSource),
			contradicted: item.contradicted === true
		}));
}

const evidence = (source: CandidateSource | undefined) =>
	Boolean(source && ((source.identifiers ?? []).length > 0 || source.named_in_text));

/**
 * The rows of a verdict's entry: one per property with candidates. `waiting`: the run waits
 * for a person (the open rows ask them); `space`: where the document lies (a space the verdict
 * leaves it in has no value of its own).
 */
export function matrixOf(
	verdict: LogEntry | undefined,
	waiting: boolean,
	space: string,
	lookup: Lookup | null,
	viewer: Viewer
): MatrixRow[] {
	const checks = list(object(verdict?.output).fields).map(object);
	return FIELDS.flatMap((field) => {
		const check = checks.find((entry) => entry.field === field);
		if (!check) return [];
		const candidates = candidatesOf(check);
		if (candidates.length === 0) return [];
		const open = check.outcome !== 'ok';
		const focus = open
			? (check.suggestion ?? candidates[0].value)
			: (check.value ?? (field === 'space' ? space : null));
		// An open check without a suggestion asks about its best candidate.
		const chosen =
			candidates.find((candidate) => candidate.value !== null && candidate.value === focus) ??
			(open && !check.suggestion ? candidates[0] : undefined);
		const name = (candidate: Candidate) =>
			typeof candidate.value === 'string'
				? describeValue(candidate.value, lookup)
				: candidate.label;
		const cells = SIGNAL_NODES.map((signal): MatrixCell => {
			const label = NODE_LABELS[signal]();
			const source = chosen?.sources.find((entry) => entry.signal === signal);
			const say = source
				? sourceChips(source)
						.map((chip) => chip.text)
						.join(', ')
				: '';
			if (evidence(source) || source?.names) {
				return {
					signal,
					kind: evidence(source) ? 'evidence' : 'names',
					title: m.matrix_cell_says({ signal: label, say })
				};
			}
			const other = candidates.find(
				(candidate) =>
					candidate !== chosen &&
					candidate.sources.some((entry) => entry.signal === signal && entry.names)
			);
			if (other) {
				const value = name(other);
				return chosen?.contradicted
					? {
							signal,
							kind: 'contradicts',
							title: m.matrix_cell_contradicts({ signal: label, value })
						}
					: { signal, kind: 'other', title: m.matrix_cell_other({ signal: label, value }) };
			}
			// Too unsure to name anything: what it measured, for this value or another.
			const weak =
				source ??
				candidates
					.map((candidate) => ({
						candidate,
						found: candidate.sources.find((entry) => entry.signal === signal)
					}))
					.find((entry) => entry.found)?.found;
			const holder = candidates.find((candidate) => weak && candidate.sources.includes(weak));
			return {
				signal,
				kind: 'silent',
				title:
					weak && holder
						? m.matrix_cell_says({
								signal: label,
								say: `${name(holder)} ${sourceChips(weak)
									.map((chip) => chip.text)
									.join(', ')}`
							})
						: m.matrix_cell_silent({ signal: label })
			};
		});
		return [
			{
				field,
				label: fieldLabel(field, lookup),
				value: valueOf(field, focus, chosen, open, space, lookup, viewer),
				open,
				cells,
				chip: chipOf(open, waiting, chosen, cells)
			}
		];
	});
}

function valueOf(
	field: string,
	focus: unknown,
	chosen: Candidate | undefined,
	open: boolean,
	space: string,
	lookup: Lookup | null,
	viewer: Viewer
): string {
	if (field === 'space' && open && typeof focus === 'string' && lookup) {
		const kind = filingKind(focus, space, lookup, viewer);
		return m.run_suggestion({ choice: choiceTitle(kind, focus, lookup, viewer) });
	}
	if (typeof focus === 'string') return describeValue(focus, lookup);
	return chosen?.label || m.value_unset();
}

function chipOf(
	open: boolean,
	waiting: boolean,
	chosen: Candidate | undefined,
	cells: readonly MatrixCell[]
): string {
	if (open) return waiting ? m.matrix_chip_question() : m.matrix_chip_unsure();
	const facts = chosen?.sources.find((source) => source.signal === 'signal_facts');
	if ((facts?.identifiers ?? []).length > 0) return m.matrix_chip_identifier();
	if (facts?.named_in_text) return m.matrix_chip_named();
	const naming = cells.filter((cell) => cell.kind === 'names' || cell.kind === 'evidence').length;
	return naming === 1
		? m.matrix_chip_signal_one()
		: m.matrix_chip_signals({ count: String(naming) });
}
