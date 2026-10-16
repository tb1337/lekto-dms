import { render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import WithDialogs from '#lib/testing/WithDialogs.svelte';

const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const RULE = '0199a6c4-0000-7000-8000-0000000000f1';
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
		expires_at: '2026-10-15T12:00:00Z',
		csrf_token: 'token'
	});
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		if (path === `/api/v1/document-types/${PAYSLIP}`) {
			return json({
				id: PAYSLIP,
				name: 'Lohnabrechnung',
				description: null,
				title_pattern: "{{ document_date | date: '%Y/%m' }}",
				created_at: '2026-10-13T12:00:00Z'
			});
		}
		if (path === '/api/v1/rules') {
			return json([{ id: RULE, name: 'Lohnabrechnung', managed_by_document_type_id: PAYSLIP }]);
		}
		if (path === '/api/v1/fields') return json([]);
		if (path === '/api/v1/documents') return json({ items: [], next_cursor: null });
		return json({ used: [], rendered: null, missing: null, error: null });
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	masterDataDialogs.close();
	session.clear();
	vi.unstubAllGlobals();
	window.document.body.style.pointerEvents = '';
});

describe('MasterDataDialogHost', () => {
	it('opens a document type from anywhere and links the rule of its pattern', async () => {
		render(WithDialogs);
		masterDataDialogs.open('document-types', PAYSLIP);
		expect(await screen.findByDisplayValue('Lohnabrechnung')).toBeTruthy();
		const link = await screen.findByRole('link', { name: m.master_title_rule() });
		expect(link.getAttribute('href')).toContain(`/rules/${RULE}`);
	});

	it('opens a type a list hands over whole, without loading it again', async () => {
		render(WithDialogs);
		masterDataDialogs.open('document-types', {
			id: PAYSLIP,
			name: 'Lohnabrechnung',
			description: null,
			title_pattern: null,
			created_at: '2026-10-13T12:00:00Z'
		});
		expect(await screen.findByDisplayValue('Lohnabrechnung')).toBeTruthy();
		expect(await screen.findByRole('link', { name: m.master_title_rule() })).toBeTruthy();
		const paths = fetchMock.mock.calls.map((call) => new URL(call[0].url).pathname);
		expect(paths).not.toContain(`/api/v1/document-types/${PAYSLIP}`);
	});

	it('has no link back to the rule it was opened from', async () => {
		render(WithDialogs);
		masterDataDialogs.open('document-types', PAYSLIP, { fromRule: RULE });
		expect(await screen.findByDisplayValue('Lohnabrechnung')).toBeTruthy();
		expect(screen.queryByRole('link', { name: m.master_title_rule() })).toBeNull();
		const paths = fetchMock.mock.calls.map((call) => new URL(call[0].url).pathname);
		expect(paths).not.toContain('/api/v1/rules');
	});
});
