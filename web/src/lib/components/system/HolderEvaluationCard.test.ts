import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { kindLabel } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';
import { fakeApi } from '#lib/testing/documents.ts';
import { goTo, testPage } from '#lib/testing/page-state.svelte.ts';
import HolderEvaluationCard from './HolderEvaluationCard.svelte';

vi.mock('$app/navigation', async () => ({
	goto: (await import('#lib/testing/page-state.svelte.ts')).fakeGoto
}));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

afterEach(() => {
	vi.unstubAllGlobals();
	goTo('/ui/system?tab=automation');
});

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

	it('opens the cases behind a number, each value showing its documents in the Beam', async () => {
		const DOC = '0199a6c4-0000-7000-8000-0000000000d1';
		const api = fakeApi({
			'GET /api/v1/automation/holders': () => ({
				kinds: [{ kind: 'iban', ...tally({ right: 41, learned_rejected: 2 }) }],
				recommendation: tally({ right: 40 })
			}),
			'GET /api/v1/automation/holders/cases': (_, url) => {
				expect(Object.fromEntries(url.searchParams)).toEqual({
					measure: 'iban',
					outcome: 'learned_rejected'
				});
				return {
					cases: [
						{
							kind: 'iban',
							value: 'DE89370400440532013000',
							ref: 'r-1',
							contact_id: 'c-1',
							contact: 'Musterbank AG',
							confirmed: false,
							document_ids: [DOC, 'd-2']
						}
					]
				};
			}
		});
		vi.stubGlobal('fetch', api);
		goTo('/ui/system?tab=automation');
		render(HolderEvaluationCard);
		const table = await screen.findByRole('table');
		const [iban, recommendation] = within(table).getAllByRole('row').slice(1);
		// "Stimmt" and the noughts stay numbers; a number above nought opens its cases.
		expect(within(recommendation).queryAllByRole('button')).toEqual([]);
		const number = within(iban).getByRole('button', {
			name: m.holders_cases_open({
				count: '2',
				measure: kindLabel('iban'),
				outcome: m.holders_learned_rejected()
			})
		});
		await userEvent.click(number);
		expect(testPage.state.holders).toEqual({ measure: 'iban', outcome: 'learned_rejected' });
		const dialog = await screen.findByRole('dialog');
		expect(dialog.textContent).toContain(m.holders_cases_learned_rejected());
		const value = await within(dialog).findByRole('button', {
			name: m.holders_cases_view({ value: 'DE89 3704 0044 0532 0130 00' })
		});
		expect(dialog.textContent).toContain('Musterbank AG');
		expect(dialog.textContent).toContain(m.holders_cases_rejected());
		expect(dialog.textContent).toContain(m.master_documents({ count: '2' }));
		await userEvent.click(value);
		expect(testPage.state.beam).toMatchObject({
			ids: [DOC, 'd-2'],
			index: 0,
			source: { kind: 'fact', identifier: 'iban', ref: 'r-1' }
		});
		// The dialog stays under the Beam, in the same history entry.
		expect(testPage.state.holders).toEqual({ measure: 'iban', outcome: 'learned_rejected' });
	});
});
