import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { fakeApi } from '#lib/testing/documents.ts';
import { choose } from '#lib/testing/select.ts';
import FactFilter from './FactFilter.svelte';

describe('FactFilter', () => {
	it('adds a fact by its kind, value (by its reference) and role, and lets one go', async () => {
		const asked: unknown[] = [];
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'POST /api/v1/identifiers/refs': async (request) => {
					const body = await request.json();
					asked.push(body);
					if (body.value === 'kaputt') {
						return new Response(
							JSON.stringify({ title: 'Unprocessable', status: 422, detail: 'not one' }),
							{ status: 422, headers: { 'content-type': 'application/problem+json' } }
						);
					}
					return { kind: body.kind, value: 'R1001', ref: 'UjEwMDE' };
				}
			})
		);
		const onchange = vi.fn();
		const user = userEvent.setup();
		render(FactFilter, {
			props: { facts: ['::refers'], admin: false, onchange }
		});
		expect(screen.getByText(m.filter_fact_any_kind() + ' · ' + m.fact_role_refers())).toBeTruthy();
		const add = screen.getByRole('button', { name: m.filter_fact_add() });
		// A value needs its kind: without one there is nothing to type it in.
		expect(screen.getByRole('textbox', { name: m.facts_decide_value() })).toHaveProperty(
			'disabled',
			true
		);
		await choose(
			user,
			screen.getByRole('combobox', { name: m.facts_add_kind() }),
			'invoice_number'
		);
		const value = screen.getByRole('textbox', { name: m.facts_decide_value() });
		await user.type(value, 'kaputt');
		await user.click(add);
		expect(await screen.findByText('not one')).toBeTruthy();
		expect(onchange).not.toHaveBeenCalled();
		await user.clear(value);
		await user.type(value, 'R-1001');
		await user.click(add);
		// The value goes to the API in a body; the filter names it by its reference only.
		await vi.waitFor(() =>
			expect(onchange).toHaveBeenLastCalledWith(['::refers', 'invoice_number:UjEwMDE:'])
		);
		expect(asked.at(-1)).toEqual({ kind: 'invoice_number', value: 'R-1001' });
		await user.click(
			screen.getByRole('button', {
				name: m.filter_remove({ name: m.filter_fact_any_kind() + ' · ' + m.fact_role_refers() })
			})
		);
		expect(onchange).toHaveBeenLastCalledWith([]);
		// A person's kinds are for admins only.
		const kinds = screen.getByRole('combobox', { name: m.facts_add_kind() });
		await expect(choose(user, kinds, 'tax_id')).rejects.toThrow();
	});
});
