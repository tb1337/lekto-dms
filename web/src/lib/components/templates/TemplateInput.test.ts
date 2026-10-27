import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { TEMPLATES_GUIDE } from '#lib/templates/guide.ts';
import TemplateInput from './TemplateInput.svelte';

const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
const previews: Record<string, unknown>[] = [];
const listed: URL[] = [];

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
	listed.length = 0;
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const url = new URL(request.url);
		if (url.pathname === '/api/v1/fields') {
			return json([
				field('f1', 'LA_Brutto', 'la_brutto', [PAYSLIP]),
				field('f2', 'Betrag', 'betrag', ['other'])
			]);
		}
		if (url.pathname === '/api/v1/documents') {
			listed.push(url);
			return json({
				items: [{ id: 'd1', title: 'Lohn März', original_filename: 'lohn-03.pdf' }],
				next_cursor: null
			});
		}
		if (url.pathname === '/api/v1/templates/preview') {
			const body = await request.json();
			previews.push(body);
			if (body.template.includes('netto')) {
				return json({
					used: [],
					rendered: null,
					missing: null,
					error: 'unknown value field.netto',
					values: null
				});
			}
			if (body.field_id && body.template === 'zwölf') {
				const unreadable = { rendered: 'zwölf', read: null, unreadable: true };
				return json({ used: [], missing: null, error: null, values: null, ...unreadable });
			}
			const values = body.document_id
				? {
						contact: 'Stadtwerke',
						'field.la_brutto': '3.650,00 EUR',
						'facts.invoice_number': 'RE-2026-0412'
					}
				: null;
			const rendered = body.document_id
				? body.template.replace('{{ field.la_brutto }}', '3.650,00 EUR')
				: null;
			const read = body.field_id && rendered ? { amount: '3650.00', currency: 'EUR' } : null;
			return json({ used: [], rendered, missing: null, error: null, values, read });
		}
		return json({}, 404);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
	// bits-ui frees the page a moment after a dialog closed; the next test must not wait for it.
	window.document.body.style.pointerEvents = '';
});

describe('TemplateInput', () => {
	it('is red with the reason when the server finds the template invalid', async () => {
		render(TemplateInput, { id: 'title', label: 'Title', value: '{{ field.netto }}' });
		await waitFor(() => expect(screen.getByText('unknown value field.netto')).toBeTruthy());
		expect(screen.getByLabelText('Title').getAttribute('aria-invalid')).toBe('true');
		// Checked without a document: a rule's template may use every field.
		expect(previews.at(-1)).toEqual({
			template: '{{ field.netto }}',
			document_type_id: null,
			purpose: 'rule'
		});
	});

	it('keeps the verdict on the newest template when an older answer arrives late', async () => {
		let answerSlow!: () => void;
		const slow = new Promise<void>((resolve) => (answerSlow = resolve));
		const base = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) => {
			if (new URL(request.url).pathname === '/api/v1/templates/preview') {
				const body = await request.clone().json();
				if (body.template === 'slow') {
					previews.push(body);
					await slow;
					return json({
						used: [],
						rendered: null,
						missing: null,
						error: 'late error',
						values: null
					});
				}
			}
			return base(request);
		});
		const props = { id: 'title', label: 'Title' };
		const { rerender } = render(TemplateInput, { ...props, value: 'slow' });
		await waitFor(() => expect(previews.at(-1)?.template).toBe('slow'));
		await rerender({ ...props, value: 'fast' });
		await waitFor(() => expect(previews.at(-1)?.template).toBe('fast'));
		// The newest template is fine; the verdict on the one before must not overwrite that.
		answerSlow();
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText('late error')).toBeNull();
		expect(screen.getByLabelText('Title').getAttribute('aria-invalid')).not.toBe('true');
	});

	it('asks for no fields when the page gives them', async () => {
		const user = userEvent.setup();
		render(TemplateInput, {
			id: 'title',
			label: 'Title',
			value: '',
			fields: [field('f3', 'Netto', 'netto', null)] as unknown as FieldDefinition[]
		});
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		expect(
			await within(sheet).findByRole('button', { name: m.template_insert({ name: 'Netto' }) })
		).toBeTruthy();
		const asked = fetchMock.mock.calls.map(([request]) => new URL(request.url).pathname);
		expect(asked).not.toContain('/api/v1/fields');
	});

	it('opens the editor with a document of the type, its values, and applies the draft', async () => {
		const user = userEvent.setup();
		render(TemplateInput, {
			id: 'pattern',
			label: m.master_title_pattern(),
			documentType: PAYSLIP,
			value: 'Lohn '
		});
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		const draft = (await within(sheet).findByLabelText(m.template_editor())) as HTMLTextAreaElement;
		expect(draft.value).toBe('Lohn ');
		// The newest document of the type is the reference; the list shows what it has.
		expect(await within(sheet).findByText('Lohn März')).toBeTruthy();
		expect(listed[0].searchParams.get('document_type_id')).toBe(PAYSLIP);
		expect(await within(sheet).findByText('3.650,00 EUR')).toBeTruthy();
		// Only the fields of the type; the facts the document shows.
		expect(within(sheet).queryByText('field.betrag')).toBeNull();
		expect(within(sheet).getByText('RE-2026-0412')).toBeTruthy();
		expect(within(sheet).queryByText('facts.order_number')).toBeNull();

		draft.setSelectionRange(5, 5);
		await user.click(
			within(sheet).getByRole('button', { name: m.template_insert({ name: 'LA_Brutto' }) })
		);
		expect(draft.value).toBe('Lohn {{ field.la_brutto }}');
		await user.click(within(sheet).getByRole('button', { name: 'upcase' }));
		expect(draft.value).toBe('Lohn {{ field.la_brutto | upcase }}');
		expect(await within(sheet).findByText(m.template_preview({ title: 'Lohn März' }))).toBeTruthy();
		await waitFor(() =>
			expect(previews.at(-1)).toEqual({
				template: 'Lohn {{ field.la_brutto | upcase }}',
				document_id: 'd1',
				document_type_id: PAYSLIP,
				purpose: 'rule'
			})
		);

		await user.click(within(sheet).getByRole('button', { name: m.template_editor_apply() }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect((screen.getByLabelText(m.master_title_pattern()) as HTMLTextAreaElement).value).toBe(
			'Lohn {{ field.la_brutto | upcase }}'
		);
	});

	it('offers a new type the fields it is created with, besides the global ones', async () => {
		// Issue #73: a type and its fields are created together, so its pattern may name them.
		const user = userEvent.setup();
		render(TemplateInput, {
			id: 'pattern',
			label: m.master_title_pattern(),
			documentType: null,
			extraFields: ['f2'],
			value: ''
		});
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		expect(
			await within(sheet).findByRole('button', { name: m.template_insert({ name: 'Betrag' }) })
		).toBeTruthy();
		expect(
			within(sheet).queryByRole('button', { name: m.template_insert({ name: 'LA_Brutto' }) })
		).toBeNull();
	});

	it('links the documentation of templates from the editor', async () => {
		const user = userEvent.setup();
		render(TemplateInput, { id: 'pattern', label: m.master_title_pattern(), value: '' });
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		const link = within(sheet).getByRole('link', { name: m.template_guide() });
		expect(link.getAttribute('href')).toBe(TEMPLATES_GUIDE);
		expect(link.getAttribute('target')).toBe('_blank');
		expect(link.getAttribute('rel')).toContain('noopener');
	});

	it('drops the draft when the editor is cancelled', async () => {
		const user = userEvent.setup();
		render(TemplateInput, { id: 'reason', label: 'Reason', value: 'Check' });
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		const draft = (await within(sheet).findByLabelText(m.template_editor())) as HTMLTextAreaElement;
		await user.type(draft, ' it');
		await user.click(within(sheet).getByRole('button', { name: m.cancel() }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect((screen.getByLabelText('Reason') as HTMLTextAreaElement).value).toBe('Check');
	});
});

describe('a template that sets a field', () => {
	const amount = field('f1', 'LA_Brutto', 'la_brutto', null) as unknown as FieldDefinition;

	it('is red when text that uses no value cannot be read as the field', async () => {
		// `props`: a mount option is called `target` too.
		render(TemplateInput, { props: { id: 'v', label: 'Value', value: 'zwölf', target: amount } });
		const message = m.template_unreadable({ type: m.field_def_type_amount() });
		await waitFor(() => expect(screen.getByText(message)).toBeTruthy());
		expect(previews.at(-1)).toMatchObject({ template: 'zwölf', field_id: 'f1' });
	});

	it('shows in the editor what the field gets from the reference document', async () => {
		const user = userEvent.setup();
		render(TemplateInput, {
			props: {
				id: 'v',
				label: 'Value',
				value: '{{ field.la_brutto }}',
				target: amount,
				fields: [amount]
			}
		});
		await user.click(await screen.findByRole('button', { name: m.template_editor_open() }));
		const sheet = await screen.findByRole('dialog');
		const read = m.template_read({ type: m.field_def_type_amount() });
		expect(await within(sheet).findByText(read, { exact: false })).toBeTruthy();
		expect(previews.at(-1)).toMatchObject({ document_id: 'd1', field_id: 'f1' });
	});
});
