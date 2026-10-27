// The names of the jobs' kinds and states and what the table says of a job.
import { afterEach, describe, expect, it } from 'vitest';
import { getLocale, setLocale } from '#lib/paraglide/runtime.js';
import {
	countOf,
	jobDue,
	jobRun,
	jobWait,
	kindLabel,
	totals,
	workersStill,
	type Job
} from './jobs.ts';

const before = getLocale();
afterEach(() => setLocale(before, { reload: false }));

const NOW = new Date('2026-10-24T12:00:00Z');

function job(overrides: Partial<Job>): Job {
	return {
		id: 'j1',
		kind: 'pipeline.node',
		state: 'due',
		attempts: 0,
		run_at: '2026-10-24T11:54:00Z',
		started_at: null,
		finished_at: null,
		document: null,
		document_hidden: false,
		node: null,
		contact: null,
		error: null,
		retry: null,
		...overrides
	};
}

const index = { kind: 'search.index', running: 1, due: 74, planned: 0, failed: 0, done: 2300 };
const logo = { kind: 'contacts.logo', running: 0, due: 2, planned: 1, failed: 1, done: 41 };

describe('the jobs', () => {
	it('name their kinds in the language, a kind unknown here as it is', () => {
		setLocale('de', { reload: false });
		expect(kindLabel('search.index')).toBe('Suchindex');
		expect(kindLabel('pipeline.node')).toBe('Verarbeitungsschritt');
		expect(kindLabel('future.kind')).toBe('future.kind');
		expect(kindLabel('toString')).toBe('toString');
	});

	it('count by state', () => {
		expect(countOf(index, ['running', 'due', 'planned'])).toBe(75);
		expect(totals([index, logo])).toEqual({
			running: 1,
			due: 76,
			planned: 1,
			failed: 1,
			done: 2341
		});
	});

	it('say when one is due, how long it waited and how long it ran', () => {
		setLocale('de', { reload: false });
		const running = job({ state: 'running', attempts: 1, started_at: '2026-10-24T11:59:46Z' });
		expect(jobDue(running, NOW)).toMatch(/11:54|13:54/); // the time it fell due, in the zone
		expect(jobWait(running, NOW)).toBe('5m\u00a046s');
		expect(jobRun(running, NOW)).toBe('bisher 14s');
		expect(jobDue(job({}), NOW)).toBe('seit 6m\u00a00s');
		expect(jobWait(job({}), NOW)).toBe('bisher 6m\u00a00s');
		expect(jobRun(job({}), NOW)).toBe('–');
		const retry = job({ state: 'planned', attempts: 1, run_at: '2026-10-24T12:00:25Z' });
		expect(jobDue(retry, NOW)).toBe('in 25s · 2. Versuch');
		expect(jobWait(retry, NOW)).toBe('–');
		const later = job({ state: 'planned', run_at: '2026-10-24T13:00:00Z' });
		expect(jobDue(later, NOW)).toBe('in 1h\u00a00m');
		const failed = job({
			state: 'failed',
			attempts: 3,
			started_at: '2026-10-24T09:11:50Z',
			finished_at: '2026-10-24T09:12:00Z'
		});
		expect(jobDue(failed, NOW)).toMatch(/24\.10\.26/);
		expect(jobRun(failed, NOW)).toBe('10s');
		const done = job({
			state: 'done',
			started_at: '2026-10-24T11:54:03Z',
			finished_at: '2026-10-24T11:54:05Z'
		});
		expect(jobWait(done, NOW)).toBe('3s');
		expect(jobRun(done, NOW)).toBe('2s');
	});

	it('tell when the workers stand still', () => {
		const summary = {
			kinds: [index],
			last_started_at: '2026-10-24T11:59:58Z',
			now: NOW.toISOString(),
			kept_since: '2026-10-17T12:00:00Z'
		};
		expect(workersStill(summary)).toBe(false);
		expect(workersStill({ ...summary, last_started_at: '2026-10-24T11:55:00Z' })).toBe(true);
		expect(workersStill({ ...summary, last_started_at: null })).toBe(true);
		const idle = { ...index, running: 0, due: 0 };
		expect(workersStill({ ...summary, kinds: [idle], last_started_at: null })).toBe(false);
	});
});
