import { describe, expect, it } from 'vitest';
import { formatDate } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';
import { axisOf, inMonth, laneTitle, type StreamLane, type StreamOut } from './stream.ts';

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
	folded: false,
	...changes
});

const stream = (lanes: StreamLane[]): StreamOut => ({ lanes, truncated: false });

const lookup = {
	contacts: [{ id: 'c1', name: 'Stadtwerke' }],
	documentTypes: [
		{ id: 't1', name: 'Abschlag' },
		{ id: 't2', name: 'Reklamation' }
	]
} as never;

describe('the stream', () => {
	it('lays the months from the oldest to the expected one', () => {
		const found = stream([
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
		]);
		expect(axisOf(found)).toEqual([
			{ kind: 'month', month: '2026-06' },
			{ kind: 'month', month: '2026-07' },
			{ kind: 'month', month: '2026-08' },
			{ kind: 'month', month: '2026-09' },
			{ kind: 'month', month: '2026-10' }
		]);
		expect(inMonth(found.lanes[0], '2026-09').map((item) => item.id)).toEqual(['b']);
	});

	it('folds a long stretch without documents into one gap, so an old contract stays in sight', () => {
		const found = stream([
			lane({
				documents: [doc('a', '2026-07-15'), doc('b', '2026-09-15')],
				target: doc('v', '2021-06-01')
			}),
			lane({ kind: 'single', documents: [doc('x', '2026-04-02')] })
		]);
		expect(axisOf(found)).toEqual([
			{ kind: 'month', month: '2021-06' },
			{ kind: 'gap', months: 57, from: '2021-07', to: '2026-03' },
			{ kind: 'month', month: '2026-04' },
			{ kind: 'month', month: '2026-05' },
			{ kind: 'month', month: '2026-06' },
			{ kind: 'month', month: '2026-07' },
			{ kind: 'month', month: '2026-08' },
			{ kind: 'month', month: '2026-09' }
		]);
	});

	it('names a series by contact and type, a branch by its first type and month, the rest Einzeln', () => {
		expect(laneTitle(lane({}), lookup)).toBe('Stadtwerke · Abschlag');
		const month = formatDate('2026-08-01', { month: 'short', year: '2-digit' });
		const branch = lane({ kind: 'branch', documents: [doc('r', '2026-08-01', 't2')] });
		expect(laneTitle(branch, lookup)).toBe(`Reklamation · ${month}`);
		const untyped = lane({ kind: 'chain', documents: [doc('Mahnung', '2026-08-20', null)] });
		expect(laneTitle(untyped, lookup)).toBe(`Mahnung · ${month}`);
		expect(laneTitle(lane({ kind: 'single' }), lookup)).toBe(m.stream_single());
	});

	it('names a series by its first document or number while the names are not at hand', () => {
		expect(laneTitle(lane({ number: 'V-1', documents: [doc('a', '2026-07-15')] }), null)).toBe('a');
		expect(laneTitle(lane({ number: 'V-1' }), null)).toBe('V-1');
	});
});
