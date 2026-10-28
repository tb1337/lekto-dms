import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { kindLabel } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';
import { fakeApi } from '#lib/testing/documents.ts';
import HolderEvaluationCard from './HolderEvaluationCard.svelte';

afterEach(() => vi.unstubAllGlobals());

const tally = (changes: Record<string, number> = {}) => ({
	right: 0,
	learned_rejected: 0,
	refused_confirmed: 0,
	unclear: 0,
	unread: 0,
	...changes
});

describe('the holders against the decisions', () => {
	it('shows each kind in a fixed order, the wrong in red, and the recommendation last', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/automation/holders': () => ({
					kinds: [
						{ kind: 'creditor_id', ...tally({ right: 2, unclear: 1 }) },
						{ kind: 'email_domain', ...tally({ unread: 15 }) },
						{ kind: 'iban', ...tally({ right: 29 }) },
						// A kind this build does not know stands after the known ones, as it comes.
						{ kind: 'lei', ...tally({ unread: 1 }) },
						{ kind: 'vat_id', ...tally({ unread: 3 }) }
					],
					recommendation: tally({ right: 40, learned_rejected: 3, unclear: 25 })
				})
			})
		);
		render(HolderEvaluationCard);
		const table = await screen.findByRole('table');
		const rows = within(table).getAllByRole('row').slice(1);
		expect(rows.map((row) => row.querySelector('td')?.textContent?.trim())).toEqual([
			kindLabel('iban'),
			kindLabel('creditor_id'),
			kindLabel('vat_id'),
			kindLabel('email_domain'),
			'lei',
			m.holders_recommendation()
		]);
		expect(rows[0].textContent).toContain(m.holders_of({ count: '29' }));
		const cells = within(rows[5]).getAllByRole('cell');
		expect(cells[1].textContent).toContain(m.holders_of({ count: '43' }));
		expect(cells[2].className).toContain('text-lane-red-foreground');
		expect(cells[3].className).not.toContain('text-lane-red-foreground');
		// Nothing told yet: no share, no ways wrong.
		expect(within(rows[2]).getAllByRole('cell')[1].textContent?.trim()).toBe('–');
	});
});
