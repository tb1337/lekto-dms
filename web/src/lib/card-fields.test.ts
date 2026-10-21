import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import CardFields from '#lib/components/CardFields.svelte';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { cardLines, dueOf, dueText } from './card-fields.ts';

const TODAY = new Date(2026, 9, 20, 15, 30); // 20 October 2026, afternoon

function field(id: string, name: string, data_type: string): FieldDefinition {
	return { id, name, data_type } as unknown as FieldDefinition;
}

const AMOUNT = field('a', 'Betrag', 'amount');
const DUE = field('d', 'Fällig am', 'date');
const NOTE = field('n', 'Notiz', 'text');
const COUNT = field('c', 'Anzahl', 'number');

describe('a deadline', () => {
	it('is overdue once passed, soon within seven days, later after', () => {
		expect(dueOf('2026-10-19', TODAY)).toMatchObject({ state: 'overdue', days: -1 });
		expect(dueOf('2026-10-20', TODAY)).toMatchObject({ state: 'soon', days: 0 });
		expect(dueOf('2026-10-27', TODAY)).toMatchObject({ state: 'soon', days: 7 });
		expect(dueOf('2026-10-28', TODAY)).toMatchObject({ state: 'later', days: 8 });
	});

	it('says in words how soon', () => {
		expect(dueText(dueOf('2026-10-16', TODAY))).toBe(m.due_overdue({ count: '4' }));
		expect(dueText(dueOf('2026-10-19', TODAY))).toBe(m.due_overdue_one());
		expect(dueText(dueOf('2026-10-20', TODAY))).toBe(m.due_today());
		expect(dueText(dueOf('2026-10-21', TODAY))).toBe(m.due_tomorrow());
		expect(dueText(dueOf('2026-10-25', TODAY))).toBe(m.due_in({ count: '5' }));
		expect(dueText(dueOf('2026-11-15', TODAY))).toContain('15');
	});
});

describe('the lines of a card', () => {
	it('puts an amount and the deadline on one line, the rest as name and value', () => {
		const values = { a: { amount: '89.00', currency: 'EUR' }, d: '2026-10-16', c: '1250', n: '' };
		const lines = cardLines(values, [NOTE, AMOUNT, COUNT, DUE], 'd', TODAY);
		expect(lines).toHaveLength(2);
		expect(lines[0]).toMatchObject({ kind: 'pay', due: { state: 'overdue', days: -4 } });
		expect(lines[0].kind === 'pay' && lines[0].amount).toMatch(/89/);
		// The empty note is left out; a number in the user's format.
		expect(lines[1]).toMatchObject({ kind: 'value', name: 'Anzahl' });
		expect(lines[1].kind === 'value' && lines[1].text).toMatch(/1.?250/);
	});

	it('shows a deadline without an amount as its own line, nothing without values', () => {
		const lines = cardLines({ d: '2026-10-25' }, [DUE, NOTE], 'd', TODAY);
		expect(lines).toEqual([
			{ kind: 'value', name: 'Fällig am', text: expect.any(String), due: expect.anything() }
		]);
		expect(cardLines({}, [AMOUNT, DUE], 'd', TODAY)).toEqual([]);
		expect(cardLines(undefined, [NOTE], null, TODAY)).toEqual([]);
	});

	it('marks a passed deadline with words and an icon, not colour alone', () => {
		const lines = cardLines(
			{ a: { amount: '89.00', currency: 'EUR' }, d: '2026-10-16' },
			[AMOUNT, DUE],
			'd',
			TODAY
		);
		const { container } = render(CardFields, { lines });
		expect(screen.getByText(m.due_overdue({ count: '4' }), { exact: false })).toBeTruthy();
		expect(container.querySelector('svg')).not.toBeNull();
		expect(container.textContent).toContain('Fällig am:');
	});
});
