import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import IdentifiersEditor from '#lib/components/IdentifiersEditor.svelte';
import { ApiError, type Problem } from '#lib/api/problem.ts';
import openapi from '../../openapi.json';
import {
	changesOf,
	IDENTIFIER_KINDS,
	kindLabel,
	NAMING_KINDS,
	numbersOf,
	PERSON_KINDS,
	refusedRow,
	rowsOf
} from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';

const stored = [
	{ kind: 'iban', value: 'DE89370400440532013000', source: 'manual', topic_id: null },
	{ kind: 'email_domain', value: 'stadtwerke.example', source: 'learned', topic_id: null },
	{ kind: 'customer_number', value: '4711', source: 'rejected', topic_id: null }
] as const;

describe('identifiers', () => {
	it('offers the kinds as the API names them', () => {
		type Kinds = Record<string, { contact: boolean; person: boolean; names_user: boolean }>;
		const kinds = (openapi as unknown as { 'x-identifier-kinds': Kinds })['x-identifier-kinds'];
		const having = (flag: 'contact' | 'person' | 'names_user') =>
			Object.keys(kinds)
				.filter((kind) => kinds[kind][flag])
				.sort();
		expect([...IDENTIFIER_KINDS].sort()).toEqual(having('contact'));
		expect([...PERSON_KINDS].sort()).toEqual(having('person'));
		expect([...NAMING_KINDS].sort()).toEqual(having('names_user'));
	});

	it('sends the entered and the rejected ones, not the learned ones', () => {
		const rows = rowsOf([...stored]);
		rows.push({ ...rows[0], key: 99, value: '  ' });
		expect(changesOf(rows)).toEqual({
			identifiers: [{ kind: 'iban', value: 'DE89370400440532013000' }],
			rejected_identifiers: [{ kind: 'customer_number', value: '4711' }]
		});
	});

	it('sends a user’s numbers with the topics their contacts enable, and the declined ones', () => {
		const rows = rowsOf([
			{ contact_id: 'c1', kind: 'personnel_number', value: ' 12345 ', topic_id: 'work' },
			{ contact_id: 'c2', kind: 'customer_number', value: 'K2002', topic_id: 'work' },
			{ contact_id: 'c2', kind: 'customer_number', value: 'K3003', source: 'rejected' },
			{ contact_id: 'c2', kind: 'customer_number', value: 'K4004', source: 'learned' },
			{ contact_id: '', kind: 'customer_number', value: 'K5005' }
		]);
		expect(numbersOf(rows, (contact) => (contact === 'c1' ? ['work'] : []))).toEqual({
			numbers: [
				{ contact_id: 'c1', kind: 'personnel_number', value: '12345', topic_id: 'work' },
				{ contact_id: 'c2', kind: 'customer_number', value: 'K2002' }
			],
			declined_numbers: [{ contact_id: 'c2', kind: 'customer_number', value: 'K3003' }]
		});
	});

	it('takes over or rejects a learned one, and allows a rejected one again', async () => {
		const rows = rowsOf([...stored]);
		render(IdentifiersEditor, { rows });
		expect(screen.getByText(m.identifier_learned())).toBeTruthy();
		// Each opens with its line.
		await userEvent.click(screen.getByRole('button', { name: /^stadtwerke\.example/ }));
		await userEvent.click(screen.getByRole('button', { name: m.identifier_reject() }));
		expect(screen.getAllByText(m.identifier_rejected())).toHaveLength(2);
		await userEvent.click(screen.getByRole('button', { name: /^4711/ }));
		await userEvent.click(screen.getByRole('button', { name: m.identifier_unblock() }));
		expect(screen.getAllByText(m.identifier_rejected())).toHaveLength(1);
		await userEvent.click(screen.getByRole('button', { name: m.identifier_add_short() }));
		expect(screen.getAllByRole('textbox', { name: m.identifier_value() })).toHaveLength(1);
	});
});

describe('the user a number belongs to', () => {
	it('sends it with customer and personnel numbers only', () => {
		const rows = rowsOf([
			{
				kind: 'customer_number',
				value: 'K-4711',
				source: 'manual',
				topic_id: null,
				user_id: 'anna'
			},
			{ kind: 'iban', value: 'DE89370400440532013000', source: 'manual', topic_id: null }
		]);
		rows[1].user_id = 'anna';
		expect(changesOf(rows).identifiers).toEqual([
			{ kind: 'customer_number', value: 'K-4711', user_id: 'anna' },
			{ kind: 'iban', value: 'DE89370400440532013000' }
		]);
	});

	it('names every kind of a person', () => {
		expect(PERSON_KINDS.map(kindLabel)).toEqual([
			m.identifier_kind_iban(),
			m.identifier_kind_tax_id(),
			m.identifier_kind_social_security_number(),
			m.identifier_kind_health_insurance_number(),
			m.identifier_kind_email_address()
		]);
	});
});

describe('the topic of an identifier', () => {
	it('is sent where the contact enables it, never with a rejected one', () => {
		const rows = rowsOf([
			{ kind: 'personnel_number', value: '4711', source: 'manual', topic_id: 'p1' },
			{ kind: 'customer_number', value: 'KV-1', source: 'manual', topic_id: 'p2' },
			{ kind: 'iban', value: 'DE89370400440532013000', source: 'rejected', topic_id: null }
		]);
		expect(changesOf(rows, ['p1'])).toEqual({
			identifiers: [
				{ kind: 'personnel_number', value: '4711', topic_id: 'p1' },
				{ kind: 'customer_number', value: 'KV-1' }
			],
			rejected_identifiers: [{ kind: 'iban', value: 'DE89370400440532013000' }]
		});
	});
});

describe('the identifier a change failed on', () => {
	const rows = rowsOf([
		{ kind: 'iban', value: 'DE89 3704 0044 0532 0130 00' },
		{ kind: 'customer_number', value: '4711' }
	]);
	const problem = (detail: string, reason: Problem['reason'] = null): ApiError =>
		new ApiError(
			409,
			{
				type: 'about:blank',
				title: 'Conflict',
				status: 409,
				detail,
				existing_document_id: null,
				space_id: null,
				open_fields: null,
				blocking_spaces: null,
				second_factor_required: null,
				reason,
				errors: null
			},
			null
		);

	it('is the one its reason names, whatever the language of the text', () => {
		const taken = problem("'DE89370400440532013000' is already an identifier of the contact 'X'", {
			code: 'identifier_of_contact',
			params: { value: 'DE89370400440532013000', contact: 'X' }
		});
		expect(refusedRow(taken, rows)?.value).toBe('DE89 3704 0044 0532 0130 00');
	});

	it('is the one the text quotes for an error without a code', () => {
		expect(refusedRow(problem("'4711' is not allowed"), rows)?.value).toBe('4711');
		expect(refusedRow(problem('something else'), rows)).toBeUndefined();
		expect(refusedRow(new Error('x'), rows)).toBeUndefined();
	});
});
