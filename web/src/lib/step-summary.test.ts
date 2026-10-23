import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import type { Node, NodeState } from '#lib/pipeline.ts';
import { byPerson, confirmationOf, stepSummary } from './step-summary.ts';

type LogEntry = components['schemas']['LogEntry'];

const JUKO = '0199a6c4-0000-7000-8000-0000000000c1';
const BAKERY = '0199a6c4-0000-7000-8000-0000000000c2';
const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const HOME = '0199a6c4-0000-7000-8000-0000000000a1';
const ANNA = '0199a6c4-0000-7000-8000-0000000000b1';
const lookup = {
	contacts: [
		{ id: JUKO, name: 'JUKO Marburg e.V.' },
		{ id: BAKERY, name: 'Schwälmer Brotladen' }
	],
	documentTypes: [{ id: PAYSLIP, name: 'Lohnabrechnung' }],
	tags: [],
	fields: [],
	spaces: [{ id: HOME, name: 'Tobi', personal_of: null, members: [] }],
	users: [{ id: ANNA, username: 'anna', display_name: 'Anna Leider', personal_space_id: null }]
} as unknown as Lookup;

const done = (node: Node): NodeState => ({
	node,
	status: 'done',
	outcome: 'ok',
	started_at: '2026-10-14T08:49:01Z',
	finished_at: '2026-10-14T08:49:05Z'
});

function entry(
	node: Node,
	output: Record<string, unknown>,
	extra: Partial<LogEntry> = {}
): LogEntry {
	return {
		node,
		run: 1,
		outcome: 'ok',
		reason: null,
		confidence: null,
		model_version: 'model',
		input: {},
		output,
		pipeline_version: 'test',
		started_at: '2026-10-14T08:49:01Z',
		duration_ms: 4000,
		...extra
	};
}

const summary = (node: Node, output: Record<string, unknown>, extra: Partial<LogEntry> = {}) =>
	stepSummary(node, done(node), entry(node, output, extra), 'completed', lookup);

describe('stepSummary', () => {
	it('tells what the reading found', () => {
		expect(summary('ocr', { pages: 7, pdfa: true, rgb: true })).toBe(
			[m.summary_pages_read({ count: '7' }), m.summary_pdfa(), m.summary_rgb()].join(' · ')
		);
		expect(summary('ocr', { pages: 1, pdfa: false, vision: { model: 'v' } })).toBe(
			[m.summary_pages_read_one(), m.summary_read_by_vision(), m.summary_not_pdfa()].join(' · ')
		);
		expect(summary('pages', { pages: 7 })).toBe(m.summary_page_images({ count: '7' }));
		expect(summary('parse', { characters: 14236 })).toBe(m.summary_characters({ count: '14,236' }));
	});

	it('tells what the signals proposed', () => {
		const proposal = {
			sender: { value: 'Schwälmer Brotladen' },
			recipient: 'Anna Leider',
			document_type: 'Lohnabrechnung'
		};
		expect(summary('signal_llm', { proposal })).toBe(
			`${m.summary_from_to({ sender: 'Schwälmer Brotladen', recipient: 'Anna Leider' })} · Lohnabrechnung`
		);
		expect(
			summary('signal_classifier', {
				contacts: [
					[JUKO, 0.52],
					[BAKERY, 0.31]
				],
				document_types: [[PAYSLIP, 0.91]]
			})
		).toBe('JUKO Marburg e.V. 52% · Lohnabrechnung 91%');
		const neighbours = [JUKO, JUKO, BAKERY, JUKO, JUKO].map((contact) => ({ contact_id: contact }));
		expect(summary('signal_neighbours', { neighbours })).toBe(
			m.summary_neighbours_most({
				documents: m.summary_neighbours({ count: '5' }),
				share: '4',
				contact: 'JUKO Marburg e.V.'
			})
		);
		expect(summary('signal_neighbours', { neighbours: [] })).toBe(m.summary_neighbours_none());
		expect(
			summary('signal_facts', {
				identifiers: [{ kind: 'personnel_number', value: '20417', contact_id: BAKERY }],
				persons: [{ user_id: ANNA, strength: 'hard' }]
			})
		).toContain('Schwälmer Brotladen');
		expect(summary('signal_classifier', { abstained: 'too few documents' })).toBe(
			`${m.signal_abstained()}: too few documents`
		);
	});

	it('tells what the verdict left open and who would not see it', () => {
		const fields = [
			{ field: 'contact', outcome: 'ok', value: BAKERY },
			{ field: 'space', outcome: 'uncertain', unseen_by: [ANNA] }
		];
		const unsure: NodeState = { ...done('judge'), outcome: 'uncertain' };
		const judged = entry('judge', { fields }, { outcome: 'uncertain' });
		const unseen = m.summary_unseen_one({ name: 'Anna Leider' });
		expect(stepSummary('judge', unsure, judged, 'review', lookup)).toBe(
			[m.summary_open({ fields: m.field_space() }), unseen].join(' · ')
		);
		// In a run that does not wait for a person, it was uncertain; open it is not.
		expect(stepSummary('judge', unsure, judged, 'completed', lookup)).toBe(
			[m.summary_unsure({ fields: m.field_space() }), unseen].join(' · ')
		);
		const both = entry(
			'judge',
			{ fields: [{ field: 'space', outcome: 'uncertain', unseen_by: [ANNA, 'someone'] }] },
			{ outcome: 'uncertain' }
		);
		expect(stepSummary('judge', unsure, both, 'review', lookup)).toContain(
			m.summary_unseen({ names: `Anna Leider, ${m.space_named_someone()}` })
		);
		expect(
			summary('judge', {
				fields: [
					{ field: 'contact', outcome: 'ok', value: BAKERY },
					{ field: 'document_type', outcome: 'ok', value: PAYSLIP }
				]
			})
		).toBe('Schwälmer Brotladen · Lohnabrechnung');
		expect(summary('judge', {}, { model_version: 'person' })).toBe(m.summary_person());
	});

	it('tells who settled what a step left uncertain or failed', () => {
		const confirmed = (before: string) =>
			summary('judge', { confirmed_by: ANNA, outcome_before: before }, { model_version: 'person' });
		expect(confirmed('uncertain')).toBe(m.summary_overruled_confirmed({ name: 'Anna Leider' }));
		expect(confirmed('failed')).toBe(m.summary_overruled_decided({ name: 'Anna Leider' }));
		// The rules filed the document where the verdict suggested: no longer open.
		const fields = [{ field: 'space', outcome: 'uncertain', unseen_by: [ANNA] }];
		expect(summary('judge', { fields }, { outcome: 'uncertain' })).toBe(
			m.summary_overruled_settled()
		);
		expect(
			confirmationOf(entry('judge', { confirmed_by: ANNA, outcome_before: 'ok' }, {}))
		).toBeNull();
		expect(
			confirmationOf(
				entry(
					'judge',
					{ confirmed_by: ANNA, outcome_before: 'failed' },
					{ model_version: 'person' }
				)
			)
		).toEqual({ by: ANNA, before: 'failed' });
	});

	it('counts the fields read and the rules that took effect', () => {
		const read = { field: 'field:a', outcome: 'ok', value: '20417' };
		const title = { field: 'title', outcome: 'ok', value: 'Lohnabrechnung' };
		expect(summary('fields', { fields: [read, read, title] })).toBe(
			m.summary_fields_read({ count: '2' })
		);
		// A field the document shows no value for is not read.
		expect(summary('fields', { fields: [read, { ...read, value: null }] })).toBe(
			m.summary_fields_partly({ read: '1', count: '2' })
		);
		expect(summary('fields', { fields: [title] })).toBe(m.summary_fields_none());
		expect(
			summary(
				'apply_rules',
				{ rules: [{ name: 'Lohn' }] },
				{ input: { trigger: 'ingest', space_id: HOME, rules: [{}, {}, {}] } }
			)
		).toBe(
			[
				m.summary_rules_arrived({ space: 'Tobi' }),
				m.summary_rules_matched_one({ count: '3' })
			].join(' · ')
		);
		expect(summary('apply_rules', { problem: 'rules move it back and forth' })).toBe(
			'rules move it back and forth'
		);
	});

	it('says nothing while a step has nothing to tell, but a waiting filing why', () => {
		const waiting: NodeState = { ...done('file'), status: 'waiting', outcome: null };
		expect(stepSummary('file', waiting, undefined, 'review', lookup)).toBe(m.summary_file_waits());
		expect(stepSummary('file', waiting, undefined, 'processing', lookup)).toBeNull();
		expect(stepSummary('ocr', null, undefined, 'completed', lookup)).toBeNull();
		const failed = entry('parse', {}, { outcome: 'failed', reason: 'no text recognised' });
		expect(stepSummary('parse', done('parse'), failed, 'failed', lookup)).toBe(
			'no text recognised'
		);
	});

	it('knows the entries of a person or of the source system', () => {
		expect(byPerson(entry('judge', {}, { model_version: 'person:0199' }))).toBe(true);
		expect(byPerson(entry('judge', {}, { model_version: 'imported' }))).toBe(true);
		expect(byPerson(entry('judge', {}, { model_version: 'qwen3:8b' }))).toBe(false);
	});
});
