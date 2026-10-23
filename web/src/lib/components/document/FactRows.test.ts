import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import FactRows from './FactRows.svelte';

const BAKERY = '0199a6c4-0000-7000-8000-0000000000c1';
const ANNA = '0199a6c4-0000-7000-8000-0000000000a1';
const lookup = {
	contacts: [{ id: BAKERY, name: 'Schwälmer Brotladen' }],
	documentTypes: [],
	tags: [],
	spaces: [],
	users: [{ id: ANNA, username: 'anna', display_name: 'Anna Leider' }]
} as unknown as Lookup;

describe('FactRows', () => {
	it('tells what the text names: contacts as chips, identifiers with their contact, persons in brackets', () => {
		render(FactRows, {
			output: {
				named: [{ name: 'N26' }, { name: 'Schwälmer Brotladen' }],
				identifiers: [{ kind: 'personnel_number', value: '20417', contact_id: BAKERY }],
				unknown_identifiers: [],
				persons: [{ user_id: ANNA, strength: 'hard' }]
			},
			lookup
		});
		expect(screen.getByText('N26')).toBeTruthy();
		expect(screen.getByText(/20417 → Schwälmer Brotladen$/)).toBeTruthy();
		expect(screen.queryByText(m.signal_unknown_identifiers())).toBeNull();
		expect(screen.getByText(m.signal_person_hard({ name: 'Anna Leider' }))).toBeTruthy();
	});

	it('says when the text names no contact and no identifier', () => {
		render(FactRows, { output: { named: [], identifiers: [] }, lookup });
		expect(screen.getAllByText(m.signal_none())).toHaveLength(2);
		expect(screen.queryByText(m.facts_persons())).toBeNull();
	});
});
