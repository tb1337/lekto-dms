import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Item } from '#lib/masterdata-api.ts';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
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
	tag('g1', ['Insurer'], null, 'contact'),
	{ ...tag('p1', ['Arbeit'], null, 'topic'), assignment: 'auto', shown: true },
	{ ...tag('p2', ['Krankenversicherung'], null, 'topic'), assignment: 'auto', shown: true }
];

const FETCHED = {
	source: 'fetched',
	domain: 'nord.example',
	stored_at: '2026-10-17T10:00:00Z',
	url: '/api/v1/contacts/c1/logo?v=1'
};
const UPLOADED = {
	...FETCHED,
	source: 'uploaded',
	domain: null,
	url: '/api/v1/contacts/c1/logo?v=2'
};
const CONTACT = {
	id: 'c1',
	name: 'Nord Versicherungsgruppe',
	aliases: [],
	identifiers: [{ kind: 'email_domain', value: 'nord.example', source: 'manual', topic_id: null }],
	group_ids: [],
	topic_ids: [],
	logo: FETCHED,
	logo_failure: null,
	created_at: '2026-10-17T12:00:00Z'
};

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
		if (path === '/api/v1/pipeline') return json({ nodes: [], vision: null, logo_fetch: true });
		if (path === '/api/v1/contacts/c1/logo' && request.method === 'PUT') {
			return json({ ...CONTACT, logo: UPLOADED, logo_failure: null });
		}
		if (path === '/api/v1/contacts/c1/logo') return new Response(null, { status: 204 });
		if (path === '/api/v1/contacts/c1/logo/fetch') return new Response(null, { status: 202 });
		if (path === '/api/v1/tags') return json(TAGS);
		if (path === '/api/v1/documents') return json({ items: [], next_cursor: null });
		return json({ used: [], rendered: null, missing: null, error: null });
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	masterDataDialogs.close();
	phone.override(null);
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

describe('a contact’s topics', () => {
	it('enables topics and lets its identifiers point to one of them', async () => {
		render(WithDialogs);
		const contact = {
			id: 'c1',
			name: 'Nord',
			aliases: [],
			identifiers: [{ kind: 'personnel_number', value: '4711', source: 'manual', topic_id: 'p1' }],
			group_ids: [],
			topic_ids: ['p1'],
			created_at: '2026-10-17T12:00:00Z'
		};
		masterDataDialogs.open('contacts', contact as unknown as Item);
		expect(await screen.findByDisplayValue('Nord')).toBeTruthy();
		const topic = screen.getByLabelText(m.identifier_topic()) as HTMLSelectElement;
		expect(topic.value).toBe('p1');
		expect([...topic.options].map((option) => option.value)).toEqual(['', 'p1']);
		// Enabling another offers it to the identifiers.
		const picker = screen.getByRole('group', { name: m.master_topics() });
		await userEvent.click(within(picker).getByLabelText('Krankenversicherung'));
		expect([...topic.options].map((option) => option.value)).toEqual(['', 'p1', 'p2']);
		await userEvent.selectOptions(topic, 'p2');
		await userEvent.click(screen.getByRole('button', { name: m.save() }));
		const patch = fetchMock.mock.calls
			.map((call) => call[0])
			.find((request) => request.method === 'PATCH');
		const body = await patch?.json();
		expect(body.topic_ids).toEqual(['p1', 'p2']);
		expect(body.identifiers).toEqual([{ kind: 'personnel_number', value: '4711', topic_id: 'p2' }]);
	});
});

describe('looks', () => {
	it('gives a tag an icon and a colour, shown in a preview', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('tags', TAGS[1] as Item);
		expect(await screen.findByDisplayValue('Health')).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.icon_choose() }));
		await user.click(screen.getByTitle('piggy-bank'));
		await user.click(screen.getByRole('radio', { name: m.color_teal() }));
		const preview = document.querySelector('[data-color="teal"]');
		expect(preview?.textContent?.trim()).toBe('Health');
		await user.click(screen.getByRole('button', { name: m.save() }));
		const patch = fetchMock.mock.calls
			.map((call) => call[0])
			.find((request) => request.method === 'PATCH');
		const body = await patch?.json();
		expect([body.icon, body.color]).toEqual(['piggy-bank', 'teal']);
	});

	it('gives a document type an icon and no colour', async () => {
		render(WithDialogs);
		masterDataDialogs.open('document-types', PAYSLIP);
		expect(await screen.findByDisplayValue('Lohnabrechnung')).toBeTruthy();
		expect(screen.getByRole('button', { name: m.icon_choose() })).toBeTruthy();
		expect(screen.queryByRole('radiogroup')).toBeNull();
	});

	it('shows where a contact’s logo came from, and uploads, removes and fetches one', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		expect(screen.getByText(/nord\.example/, { selector: 'span' })).toBeTruthy();
		const image = document.querySelector('img');
		expect(image?.getAttribute('src')).toBe(FETCHED.url);

		await user.click(await screen.findByRole('button', { name: m.logo_fetch() }));
		const requests = () => fetchMock.mock.calls.map((call) => call[0]);
		expect(requests().some((r) => r.method === 'POST' && r.url.endsWith('/logo/fetch'))).toBe(true);

		const input = document.querySelector('input[type="file"]') as HTMLInputElement;
		await user.upload(
			input,
			new File([new Uint8Array([137, 80, 78, 71])], 'logo.png', { type: 'image/png' })
		);
		const put = requests().find((r) => r.method === 'PUT');
		expect(put?.url).toContain('/api/v1/contacts/c1/logo');
		// Uploaded: never replaced by a fetched one, so no fetching is offered.
		expect(await screen.findByRole('button', { name: m.logo_remove() })).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.logo_fetch() })).toBeNull();
		expect(document.querySelector('img')?.getAttribute('src')).toBe(UPLOADED.url);

		await user.click(screen.getByRole('button', { name: m.logo_remove() }));
		expect(requests().some((r) => r.method === 'DELETE' && r.url.endsWith('/logo'))).toBe(true);
		expect(await screen.findByText(m.logo_none())).toBeTruthy();
		expect(document.querySelector('[data-initials]')?.textContent?.trim()).toBe('NV');
	});

	it('names the domains whose fetch found no logo', async () => {
		render(WithDialogs);
		const failed = {
			...CONTACT,
			logo: null,
			logo_failure: { domains: ['a.example', 'nord.example'], failed_at: '2026-10-17T10:00:00Z' }
		};
		masterDataDialogs.open('contacts', failed as unknown as Item);
		expect(await screen.findByText(/a\.example, nord\.example/)).toBeTruthy();
	});

	it('asks a new contact to be created before it gets a logo', async () => {
		render(WithDialogs);
		masterDataDialogs.open('contacts');
		expect(await screen.findByText(m.logo_after_create())).toBeTruthy();
	});
});

describe('the editor', () => {
	it('deletes a tag after asking; refused, it stays open', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		let refuse = true;
		const before = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) => {
			if (request.method === 'DELETE') {
				return refuse
					? json({ title: 'Conflict', status: 409, detail: 'the tag is in use' }, 409)
					: new Response(null, { status: 204 });
			}
			return before(request);
		});
		const changed = masterDataDialogs.changed;
		masterDataDialogs.open('tags', TAGS[2] as Item);
		expect(await screen.findByDisplayValue('Dental')).toBeTruthy();
		const remove = screen.getByRole('button', { name: m.master_delete({ name: 'Dental' }) });
		await user.click(remove);
		let confirm = await screen.findByRole('alertdialog');
		expect(within(confirm).getByText(m.tag_delete_confirm())).toBeTruthy();
		await user.click(within(confirm).getByRole('button', { name: m.delete_title() }));
		expect(await screen.findByDisplayValue('Dental')).toBeTruthy();
		expect(masterDataDialogs.request).not.toBeNull();
		await user.click(within(confirm).getByRole('button', { name: m.cancel() }));
		refuse = false;
		await user.click(remove);
		confirm = await screen.findByRole('alertdialog');
		await user.click(within(confirm).getByRole('button', { name: m.delete_title() }));
		await vi.waitFor(() => expect(masterDataDialogs.request).toBeNull());
		expect(masterDataDialogs.changed).toBe(changed + 1);
		const deleted = fetchMock.mock.calls
			.map((call) => call[0])
			.filter((r) => r.method === 'DELETE');
		expect(deleted.map((r) => new URL(r.url).pathname)).toEqual([
			'/api/v1/tags/t3',
			'/api/v1/tags/t3'
		]);
	});

	it('offers no deleting for an item still to be created', async () => {
		render(WithDialogs);
		masterDataDialogs.open('contacts');
		expect(await screen.findByText(m.logo_after_create())).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.delete_title() })).toBeNull();
	});

	it('fills a phone’s screen with a bar on top to cancel and save', async () => {
		phone.override(true);
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('tags', TAGS[1] as Item);
		expect(await screen.findByDisplayValue('Health')).toBeTruthy();
		// One way to save, in the bar on top (no footer).
		const dialog = screen.getByRole('dialog');
		const bar = within(dialog).getByRole('button', { name: m.cancel() }).parentElement!;
		expect(within(bar).getByRole('button', { name: m.editor_save_short() })).toBeTruthy();
		expect(within(dialog).getAllByRole('button', { name: m.cancel() })).toHaveLength(1);
		await user.clear(screen.getByLabelText(m.field_name()));
		await user.type(screen.getByLabelText(m.field_name()), 'Health care');
		await user.click(screen.getByRole('button', { name: m.editor_save_short() }));
		const patch = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'PATCH');
		expect(await patch?.json()).toMatchObject({ name: 'Health care' });
		await vi.waitFor(() => expect(masterDataDialogs.request).toBeNull());
	});
});
