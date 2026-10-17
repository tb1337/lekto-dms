import { render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Item } from '#lib/masterdata-api.ts';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import WithDialogs from '#lib/testing/WithDialogs.svelte';

const PAYSLIP = '0199a6c4-0000-7000-8000-0000000000e1';
const RULE = '0199a6c4-0000-7000-8000-0000000000f1';
const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function tag(id: string, path: string[], parent: string | null, scope = 'document') {
	return {
		id,
		name: path[path.length - 1],
		path,
		parent_id: parent,
		scope,
		assignment: scope === 'document' ? 'auto' : 'manual',
		shown: scope === 'document',
		created_at: '2026-10-16T12:00:00Z'
	};
}

const TAGS = [
	tag('t1', ['Insurance'], null),
	tag('t2', ['Insurance', 'Health'], 't1'),
	tag('t3', ['Insurance', 'Health', 'Dental'], 't2'),
	tag('g1', ['Insurer'], null, 'contact')
];

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
		if (path === '/api/v1/tags') return json(TAGS);
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

	it('offers a tag the tags of its scope as parents, never itself or one below it', async () => {
		render(WithDialogs);
		masterDataDialogs.open('tags', TAGS[1] as Item);
		expect(await screen.findByDisplayValue('Health')).toBeTruthy();
		const parent = screen.getByLabelText(m.tag_parent()) as HTMLSelectElement;
		const options = [...parent.options].map((option) => option.textContent?.trim());
		expect(options).toEqual([m.tag_parent_none(), 'Insurance']);
		expect(parent.value).toBe('t1');
		expect(screen.getByLabelText(m.tag_assignment_auto())).toBeTruthy();
	});

	it('asks a group neither how it is set nor for a document tag as parent', async () => {
		render(WithDialogs);
		masterDataDialogs.open('contact-groups');
		expect(await screen.findByLabelText(m.tag_parent_group())).toBeTruthy();
		expect(screen.queryByLabelText(m.tag_assignment_auto())).toBeNull();
		const parent = screen.getByLabelText(m.tag_parent_group()) as HTMLSelectElement;
		expect([...parent.options].map((option) => option.value)).toEqual(['', 'g1']);
		expect(parent.options[0].textContent?.trim()).toBe(m.tag_parent_group_none());
		expect((screen.getByLabelText(m.tag_shown()) as HTMLInputElement).checked).toBe(false);
	});
});
