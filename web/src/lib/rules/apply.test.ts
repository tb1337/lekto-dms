import { describe, expect, it } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import {
	applyRequest,
	chainLines,
	follow,
	pollDelay,
	preselected,
	type Application,
	type PreviewItem
} from './apply.ts';

const item = (id: string, conflict = false): PreviewItem => ({
	document_id: id,
	title: id,
	changes: [{ field: 'tags', old: [], new: ['t'] }],
	conflicts: conflict
		? [{ field: 'contact', kind: 'conflict', reason: 'has another contact', reasons: [] }]
		: [],
	notes: [],
	outcome: { space_id: 's0', chain: [] },
	accepted: null
});

const application = (status: Application['status'], done: number): Application => ({
	id: 'a1',
	rule_id: 'r1',
	version: 2,
	status,
	total: 3,
	done,
	applied: done,
	unchanged: 0,
	skipped: [],
	error: null,
	created_at: '2026-10-08T10:00:00Z',
	finished_at: null
});

describe('applying a rule', () => {
	const items = [item('a'), item('b', true), item('c'), item('d', true)];

	it('chooses documents without a conflict', () => {
		expect(preselected(items)).toEqual(['a', 'c']);
	});

	it('applies conflicts only with their own consent', () => {
		const request = applyRequest(2, items, new Set(['a', 'b', 'c']), new Set(['d']));
		expect(request).toEqual({ version: 2, document_ids: ['a', 'c', 'd'], accept_conflicts: ['d'] });
		expect(applyRequest(2, items, new Set(), new Set()).document_ids).toEqual([]);
	});

	it('asks every second, later every three', () => {
		expect([0, 9000, 10_000, 60_000].map(pollDelay)).toEqual([1000, 1000, 3000, 3000]);
	});

	it('follows the progress until it is done', async () => {
		const answers = [application('running', 1), application('running', 2), application('done', 3)];
		const waits: number[] = [];
		const seen: number[] = [];
		const last = await follow(
			application('queued', 0),
			async () => answers.shift()!,
			(current) => seen.push(current.done),
			new AbortController().signal,
			async (ms) => void waits.push(ms)
		);
		expect([last.status, seen, waits]).toEqual(['done', [1, 2, 3], [1000, 1000, 1000]]);
	});

	it('stops following when the page goes', async () => {
		const stop = new AbortController();
		const last = await follow(
			application('running', 1),
			async () => application('running', 2),
			() => stop.abort(),
			stop.signal,
			async () => undefined
		);
		expect(last.done).toBe(2);
	});
});

const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [{ id: 't1', name: 'Haushaltskosten' }],
	spaces: [
		{ id: 'mine', name: 'Personal', personal_of: 'u1', role: 'edit', members: [] },
		{ id: 'house', name: 'Haushalt', personal_of: null, role: 'edit', members: [] }
	],
	users: [
		{ id: 'u1', username: 'tobi', role: 'user', personal_space_id: 'mine' },
		{ id: 'u2', username: 'anna', role: 'user', personal_space_id: 'annas' }
	]
} as unknown as Lookup;

const report = (
	name: string,
	applied: { field: string; old: unknown; new: unknown }[],
	notes: { field: string; kind: 'refused' | 'skipped'; reason: string }[] = []
) => ({
	rule_id: name,
	version: 1,
	name,
	scope: 'space' as const,
	applied,
	// Without codes: the chain shows the API's text as it is (`reasons.test.ts` translates).
	notes: notes.map((note) => ({ ...note, reasons: [] }))
});

describe('the chain of a rule applied to a document', () => {
	it('names each space it enters and what its rules do there', () => {
		const lines = chainLines(
			{
				space_id: 'house',
				chain: [
					{
						space_id: 'house',
						rules: [report('Rechnungen', [{ field: 'tags', old: [], new: 't1' }])],
						moved_to: null,
						looped_to: null,
						problem: null
					}
				]
			},
			'Versorger',
			lookup,
			'u1'
		);
		expect(lines).toEqual([
			m.rule_chain_into({ space: 'Haushalt', rule: 'Versorger' }),
			m.rule_chain_then({
				change: `${m.field_tags()} Haushaltskosten`,
				rule: 'Rechnungen',
				space: 'Haushalt'
			}),
			m.rule_chain_end({ space: 'Haushalt' })
		]);
	});

	it('shows a hand-over, a loop and a space the reader cannot see', () => {
		const lines = chainLines(
			{
				space_id: 'annas',
				chain: [
					{
						space_id: 'house',
						rules: [report('An Anna', [{ field: 'space', old: 'house', new: 'annas' }])],
						moved_to: 'annas',
						looped_to: null,
						problem: null
					},
					{
						space_id: 'annas',
						rules: [
							report(
								'Weiter',
								[],
								[{ field: 'space', kind: 'refused', reason: 'no write access' }]
							),
							report('Zurück', [{ field: 'space', old: 'annas', new: 'house' }])
						],
						moved_to: null,
						looped_to: 'house',
						problem: 'rules move it back and forth'
					}
				]
			},
			'Versorger',
			lookup,
			'u1'
		);
		expect(lines).toEqual([
			m.rule_chain_into({ space: 'Haushalt', rule: 'Versorger' }),
			m.rule_chain_moved({ space: 'anna', rule: 'An Anna', from: 'Haushalt' }),
			m.rule_chain_note({
				field: m.field_space(),
				reason: 'no write access',
				rule: 'Weiter',
				space: 'anna'
			}),
			m.rule_chain_loop({ spaces: 'Haushalt → anna → Haushalt' }),
			m.rule_chain_end({ space: 'anna' })
		]);
		const hidden = chainLines({ space_id: 'elsewhere', chain: [] }, 'Versorger', lookup, 'u1');
		expect(hidden).toEqual([m.rule_chain_into({ space: m.space_unseen(), rule: 'Versorger' })]);
	});
});
