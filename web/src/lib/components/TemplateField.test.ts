import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import TemplateField from './TemplateField.svelte';

const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
const previews: unknown[] = [];

function json(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

function field(id: string, name: string, key: string, types: string[] | null) {
	return {
		id,
		name,
		key,
		data_type: 'amount',
		document_type_ids: types,
		choices: [],
		required: false,
		required_document_type_ids: [],
		description: null,
		created_at: '2026-10-13T12:00:00Z'
	};
}

beforeEach(() => {
	previews.length = 0;
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const url = new URL(request.url);
		if (url.pathname === '/api/v1/fields') {
			return json([
				field('f1', 'LA_Brutto', 'la_brutto', [PAYSLIP]),
				field('f2', 'Betrag', 'betrag', ['other']),
				field('f3', 'Notiz', 'notiz', null)
			]);
		}
		if (url.pathname === '/api/v1/documents') {
			return json({ items: [{ id: 'd1', title: 'Lohn März' }], next_cursor: null });
		}
		if (url.pathname === '/api/v1/templates/preview') {
			const body = await request.json();
			previews.push(body);
			return json(
				body.template.includes('netto')
					? { used: [], rendered: null, missing: null, error: 'unknown value field.netto' }
					: { used: ['contact'], rendered: 'Lohn 3.650,00 EUR', missing: null, error: null }
			);
		}
		return json({}, 404);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('TemplateField', () => {
	it('offers the values and the fields of the type, and inserts them', async () => {
		const user = userEvent.setup();
		render(TemplateField, { id: 'pattern', documentType: PAYSLIP, value: 'Lohn ' });
		const insert = await screen.findByRole('button', { name: 'field.la_brutto' });
		expect(screen.getByRole('button', { name: 'field.notiz' })).toBeTruthy();
		expect(screen.queryByRole('button', { name: 'field.betrag' })).toBeNull();
		await user.click(screen.getByRole('textbox'));
		await user.keyboard('{End}');
		await user.click(insert);
		expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(
			'Lohn {{ field.la_brutto }}'
		);
		await user.click(screen.getByRole('button', { name: m.field_contact() }));
		expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toContain('{{ contact }}');
	});

	it('shows what the template gives for a document of the type, or why not', async () => {
		render(TemplateField, { id: 'pattern', documentType: PAYSLIP, value: 'Lohn {{ contact }}' });
		expect(await screen.findByText('Lohn 3.650,00 EUR')).toBeTruthy();
		expect(screen.getByText(m.template_preview({ title: 'Lohn März' }))).toBeTruthy();
		expect(previews.at(-1)).toEqual({
			template: 'Lohn {{ contact }}',
			document_id: 'd1',
			document_type_id: PAYSLIP
		});
	});

	it('shows the error of an invalid template', async () => {
		render(TemplateField, { id: 'title', value: '{{ field.netto }}' });
		await waitFor(() => expect(screen.getByText('unknown value field.netto')).toBeTruthy());
		expect(screen.getByRole('textbox').getAttribute('aria-invalid')).toBe('true');
		// A rule's template: every field, no document to render it with.
		expect(screen.getByRole('button', { name: 'field.betrag' })).toBeTruthy();
		expect(previews.at(-1)).toEqual({
			template: '{{ field.netto }}',
			document_id: null,
			document_type_id: null
		});
	});
});
