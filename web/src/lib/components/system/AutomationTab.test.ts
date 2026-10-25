// The tab "Automation": the lanes of the first runs, what became of them, the times, the
// history by month and the hit rate per field, for the channels and the period chosen.
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatDuration } from '#lib/duration.ts';
import { m } from '#lib/paraglide/messages.js';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import AutomationTab from './AutomationTab.svelte';

const lanes = (green: number, yellow: number, red: number) => ({ green, yellow, red });
const verdicts = (taken: number, accepted: number, corrected: number, added: number) => ({
	taken,
	accepted,
	corrected,
	added
});

const report = {
	channels: ['api', 'web'],
	period: '12m',
	since: '2025-11-01T00:00:00Z',
	lanes: lanes(70, 24, 6),
	flow: [
		{ first_lane: 'green', lane: 'green', count: 68 },
		{ first_lane: 'green', lane: 'yellow', count: 2 },
		{ first_lane: 'yellow', lane: 'green', count: 20 },
		{ first_lane: 'yellow', lane: 'yellow', count: 4 },
		{ first_lane: 'red', lane: null, count: 6 }
	],
	decided: 40,
	untouched: 52,
	months: [
		{ start: '2026-09-01', lanes: lanes(30, 10, 5) },
		{ start: '2026-10-01', lanes: lanes(40, 14, 1) }
	],
	duration: { count: 100, median_ms: 52000, p90_ms: 245000 },
	work: { count: 100, median_ms: 38000, p90_ms: 112000 },
	steps: [
		{ node: 'receive', count: 100, median_ms: 200, p90_ms: 400 },
		{ node: 'ocr', count: 100, median_ms: 14000, p90_ms: 48000 },
		{ node: 'signal_llm', count: 100, median_ms: 11000, p90_ms: 27000 },
		{ node: 'signal_classifier', count: 100, median_ms: 300, p90_ms: 600 },
		{ node: 'judge', count: 100, median_ms: 100, p90_ms: 200 }
	],
	fields: [
		{ field: 'contact', name: null, verdicts: verdicts(28, 2, 6, 4), early: 1 },
		{ field: 'field:a1', name: 'Betrag', verdicts: verdicts(9, 1, 0, 0), early: 0 },
		{ field: 'field:a2', name: 'Frist', verdicts: verdicts(1, 0, 1, 0), early: 0 },
		{ field: 'field:a3', name: 'IBAN', verdicts: verdicts(1, 0, 0, 0), early: 0 },
		{ field: 'field:a4', name: 'Vertrag', verdicts: verdicts(0, 0, 0, 2), early: 0 }
	]
};

afterEach(() => vi.unstubAllGlobals());

function serve(body: unknown = report) {
	const api = fakeApi({ 'GET /api/v1/automation': () => body });
	vi.stubGlobal('fetch', api);
	return api;
}

describe('the automation tab', () => {
	it('shows the lanes, what became of them and how long the first runs took', async () => {
		serve();
		render(AutomationTab);
		expect(await screen.findByText(m.automation_first_green({ count: '70' }))).toBeTruthy();
		expect(screen.getByText(/^70\s?%$/)).toBeTruthy();
		expect(screen.getByText(formatDuration(52))).toBeTruthy();
		expect(
			screen.getByText(
				m.automation_duration_p90({ duration: formatDuration(245) }).replace(/\s/g, ' ')
			)
		).toBeTruthy();
		const yellow = [
			m.automation_flow_done({ count: '20' }),
			m.automation_flow_open({ count: '4' })
		];
		expect(screen.getByText(yellow.join(' · '))).toBeTruthy();
		expect(screen.getByText(m.automation_flow_running({ count: '6' }))).toBeTruthy();
		expect(screen.getByRole('img', { name: m.automation_months_label() })).toBeTruthy();
		expect(screen.getByText(m.automation_steps_signals())).toBeTruthy();
	});

	it("asks for the web and the API, 12 months, in the viewer's time zone", async () => {
		const api = serve();
		render(AutomationTab);
		await screen.findByText(m.automation_first_green({ count: '70' }));
		const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
		expect(calls(api)).toEqual([
			`GET /api/v1/automation?channel=web&channel=api&period=12m&tz=${zone}`
		]);
	});

	it('asks again for the channels and the period chosen, keeping one channel', async () => {
		const api = serve();
		render(AutomationTab);
		await screen.findByText(m.automation_first_green({ count: '70' }));
		await userEvent.click(screen.getByRole('button', { name: m.automation_channel_migration() }));
		await userEvent.click(screen.getByRole('button', { name: m.automation_period_all() }));
		await waitFor(() => expect(calls(api)).toHaveLength(3));
		expect(calls(api)[1]).toContain('channel=web&channel=api&channel=migration&period=12m');
		expect(calls(api)[2]).toContain('period=all');

		for (const name of [m.automation_channel_web(), m.automation_channel_api()]) {
			await userEvent.click(screen.getByRole('button', { name }));
		}
		await waitFor(() => expect(calls(api)).toHaveLength(5));
		await userEvent.click(screen.getByRole('button', { name: m.automation_channel_migration() }));
		const pressed = screen.getByRole('button', { name: m.automation_channel_migration() });
		expect(pressed.getAttribute('aria-pressed')).toBe('true'); // the last one stays
		expect(calls(api)).toHaveLength(5);
	});

	it('tells the hit rate per field and groups the custom fields', async () => {
		serve();
		render(AutomationTab);
		expect(
			await screen.findByText(
				m.automation_field_counts({ taken: '28', accepted: '2', corrected: '6', added: '4' })
			)
		).toBeTruthy();
		expect(screen.getByText(m.automation_hits_early({ count: '1' }))).toBeTruthy();
		const group = screen.getByRole('button', { name: new RegExp(m.automation_custom_fields()) });
		expect(group.getAttribute('aria-expanded')).toBe('true');
		expect(screen.getByText('Betrag')).toBeTruthy();
		expect(screen.queryByText('Vertrag')).toBeNull(); // the fourth, behind "more"
		await userEvent.click(
			screen.getByRole('button', { name: m.automation_custom_more({ count: '1' }) })
		);
		expect(screen.getByText('Vertrag')).toBeTruthy();
		await userEvent.click(group);
		expect(screen.queryByText('Betrag')).toBeNull();
	});

	it('says so when no first run stopped', async () => {
		serve({
			...report,
			lanes: lanes(0, 0, 0),
			flow: [],
			decided: 0,
			untouched: 0,
			months: [],
			duration: { count: 0, median_ms: null, p90_ms: null },
			work: { count: 0, median_ms: null, p90_ms: null },
			steps: [],
			fields: []
		});
		render(AutomationTab);
		expect(await screen.findByText(m.automation_none())).toBeTruthy();
		expect(screen.getByText(m.automation_hits_none())).toBeTruthy();
	});
});
