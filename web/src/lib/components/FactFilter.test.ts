import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { choose } from '#lib/testing/select.ts';
import FactFilter from './FactFilter.svelte';

describe('FactFilter', () => {
	it('adds a fact by its kind, value and role, and lets one go', async () => {
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
		await user.type(screen.getByRole('textbox', { name: m.facts_decide_value() }), 'R-1001');
		await user.click(add);
		expect(onchange).toHaveBeenLastCalledWith(['::refers', 'invoice_number:R-1001:']);
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
