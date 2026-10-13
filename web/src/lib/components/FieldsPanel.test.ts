import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import FieldsPanel from './FieldsPanel.svelte';

const INVOICE = '0199a6c4-0000-7000-8000-0000000000e1';
const REMINDER = '0199a6c4-0000-7000-8000-0000000000e2';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function json(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

beforeEach(() => {
	session.start({
		user: { id: 'admin', username: 'admin', role: 'admin' },
		method: 'password',
		expires_at: '2026-10-14T12:00:00Z',
		csrf_token: 'token'
	});
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		if (request.method === 'GET' && path === '/api/v1/fields') {
			return json([
				{
					id: 'f1',
					name: 'Rechnungsnummer',
					data_type: 'text',
					document_type_ids: [INVOICE, REMINDER],
					choices: [],
					required: false,
					required_document_type_ids: [INVOICE],
					created_at: '2026-10-13T12:00:00Z'
				}
			]);
		}
		if (request.method === 'GET' && path === '/api/v1/document-types') {
			return json([
				{ id: INVOICE, name: 'Rechnung', created_at: '2026-10-13T12:00:00Z' },
				{ id: REMINDER, name: 'Mahnung', created_at: '2026-10-13T12:00:00Z' }
			]);
		}
		return json({}, 201);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('FieldsPanel', () => {
	it('lists where a field is required', async () => {
		render(FieldsPanel);
		const required = m.field_def_required_in({ scope: 'Rechnung' });
		expect(await screen.findByText((text) => text.includes(required))).toBeTruthy();
	});

	it('makes a field required for one of its types', async () => {
		render(FieldsPanel);
		await userEvent.click(await screen.findByRole('button', { name: m.master_add_field() }));
		await userEvent.type(screen.getByLabelText(m.field_name()), 'Betrag');
		await userEvent.click(screen.getByLabelText(m.field_def_scope_global()));
		await userEvent.click(screen.getByLabelText('Mahnung'));
		const forReminder = screen.getByLabelText(m.field_def_required_for({ type: 'Mahnung' }));
		expect(
			(screen.getByLabelText(m.field_def_required_for({ type: 'Rechnung' })) as HTMLInputElement)
				.disabled
		).toBe(true);
		await userEvent.click(forReminder);
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		const post = fetchMock.mock.calls.map((call) => call[0]).find((call) => call.method === 'POST');
		expect(await post?.json()).toEqual({
			name: 'Betrag',
			data_type: 'text',
			document_type_ids: [REMINDER],
			required: false,
			required_document_type_ids: [REMINDER]
		});
	});
});
