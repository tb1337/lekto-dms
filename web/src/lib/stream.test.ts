import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { inMonth, laneTitle, monthsOf, type StreamLane, type StreamOut } from './stream.ts';

const doc = (id: string, date: string, type: string | null = 't1') => ({
	id,
	title: id,
	document_date: date,
	created_at: `${date}T10:00:00Z`,
	contact_id: 'c1',
	document_type_id: type,
	lane: 'green' as const
});

const lane = (changes: Partial<StreamLane>): StreamLane => ({
	kind: 'series',
	documents: [],
	contact_id: 'c1',
	document_type_id: 't1',
	number: null,
	target: null,
	expected: null,
	parent: null,
	joins: null,
	...changes
});

const lookup = {
	contacts: [{ id: 'c1', name: 'Stadtwerke' }],
	documentTypes: [
		{ id: 't1', name: 'Abschlag' },
		{ id: 't2', name: 'Reklamation' }
	]
} as never;

describe('the stream', () => {
	it('lays the months from the oldest to the expected one', () => {
		const stream: StreamOut = {
			lanes: [
				lane({
					documents: [doc('a', '2026-07-15'), doc('b', '2026-09-15')],
					target: doc('v', '2026-06-01'),
					expected: {
						next_date: '2026-10-15',
						next_period: null,
						state: 'soon',
						cadence: 'monthly',
						spread_days: 2
					}
				})
			],
			relations: [],
			truncated: false
		};
		expect(monthsOf(stream)).toEqual(['2026-06', '2026-07', '2026-08', '2026-09', '2026-10']);
		expect(inMonth(stream.lanes[0], '2026-09').map((item) => item.id)).toEqual(['b']);
	});

	it('names a series by contact and type, a branch by its first type, the rest Einzeln', () => {
		expect(laneTitle(lane({}), lookup)).toBe('Stadtwerke · Abschlag');
		const branch = lane({ kind: 'branch', documents: [doc('r', '2026-08-01', 't2')] });
		expect(laneTitle(branch, lookup)).toBe('Reklamation');
		expect(laneTitle(lane({ kind: 'single' }), lookup)).toBe(m.stream_single());
	});
});
