import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Item } from '#lib/masterdata-api.ts';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { choose, optionsOf, selectedValue } from '#lib/testing/select.ts';
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
	masterDataDialogs.finishAll();
	masterDataDialogs.close();
	phone.override(null);
	session.clear();
	vi.unstubAllGlobals();
	window.document.body.style.pointerEvents = '';
});

// The icon picker's panel is loaded when it opens; under a full parallel run that can take a
// while.
const LOADED = { timeout: 5000 };

/** The choice of a tag field, wider than a phone a popover: placed by measuring, which jsdom
 * does not, it counts as hidden and has no computed name; its title names it. */
async function pickerNamed(name: string): Promise<HTMLElement> {
	let found: HTMLElement | undefined;
	await waitFor(() => {
		found = screen.getAllByRole('dialog', { hidden: true }).find((dialog) => {
			const title = document.getElementById(dialog.getAttribute('aria-labelledby') ?? '');
			return title?.textContent?.trim() === name;
		});
		expect(found).toBeTruthy();
	});
	return found!;
}

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
		const parent = screen.getByLabelText(m.tag_parent());
		const options = (await optionsOf(parent)).map((option) => option.label);
		expect(options).toEqual([m.tag_parent_none(), 'Insurance']);
		expect(selectedValue(parent)).toBe('t1');
		expect(screen.getByLabelText(m.tag_assignment_auto())).toBeTruthy();
	});

	it('asks a group neither how it is set nor for a document tag as parent', async () => {
		render(WithDialogs);
		masterDataDialogs.open('contact-groups');
		expect(await screen.findByLabelText(m.tag_parent_group())).toBeTruthy();
		expect(screen.queryByLabelText(m.tag_assignment_auto())).toBeNull();
		const parent = screen.getByLabelText(m.tag_parent_group());
		const options = await optionsOf(parent);
		expect(options.map((option) => option.value)).toEqual(['', 'g1']);
		expect(options[0].label).toBe(m.tag_parent_group_none());
		expect((screen.getByLabelText(m.tag_shown()) as HTMLInputElement).checked).toBe(false);
	});
});

describe('saving', () => {
	it('creates a document type with its fields in one request', async () => {
		// Issue #73: a type and its fields are all or nothing; no second request.
		fetchMock.mockImplementation(async (request) => {
			const path = new URL(request.url).pathname;
			if (path === '/api/v1/document-types' && request.method === 'POST') {
				return json({ id: 'new', name: 'Rechnung', created_at: '2026-10-24T12:00:00Z' }, 201);
			}
			if (path === '/api/v1/fields' || path === '/api/v1/rules') return json([]);
			if (path === '/api/v1/tags') return json(TAGS);
			return json({ used: [], rendered: null, missing: null, error: null });
		});
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('document-types');
		await user.type(await screen.findByLabelText(m.field_name()), 'Rechnung');
		await user.click(screen.getByRole('button', { name: m.create() }));
		await waitFor(() => expect(fetchMock.mock.calls.some(([r]) => r.method === 'POST')).toBe(true));
		const changing = fetchMock.mock.calls
			.map(([request]) => request)
			.filter((request) => request.method !== 'GET');
		const sent = changing.map((request) => `${request.method} ${new URL(request.url).pathname}`);
		expect(sent.filter((call) => !call.endsWith('/templates/preview'))).toEqual([
			'POST /api/v1/document-types'
		]);
		const post = changing.find(
			(request) => request.method === 'POST' && request.url.endsWith('/document-types')
		)!;
		expect(await post.clone().json()).toMatchObject({ name: 'Rechnung', fields: [] });
	});
});

describe('tabs', () => {
	it('shows a contact’s identifiers in a tab of their own, counted', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		const tabs = screen.getByRole('group', {
			name: m.master_edit({ name: 'Nord Versicherungsgruppe' })
		});
		const [general, identifiers] = within(tabs).getAllByRole('button');
		expect(general.getAttribute('aria-pressed')).toBe('true');
		expect(identifiers.textContent).toContain(m.master_identifiers());
		expect(identifiers.textContent).toContain('1');
		expect(screen.queryByRole('button', { name: /^nord\.example/ })).toBeNull();
		await user.click(identifiers);
		expect(screen.getByRole('button', { name: /^nord\.example/ })).toBeTruthy();
		expect(screen.queryByDisplayValue('Nord Versicherungsgruppe')).toBeNull();
	});

	it('fetches the users a number may belong to once, not on every switch to the tab', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		const identifiers = screen.getByRole('button', {
			name: new RegExp(`^${m.master_identifiers()}`)
		});
		await user.click(identifiers);
		await user.click(screen.getByRole('button', { name: m.master_tab_general() }));
		await user.click(identifiers);
		const users = () =>
			fetchMock.mock.calls.filter((call) => new URL(call[0].url).pathname === '/api/v1/users');
		await waitFor(() => expect(users()).toHaveLength(1));
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(users()).toHaveLength(1);
	});

	it('opens the tab and the line of an identifier the API refuses', async () => {
		const user = userEvent.setup();
		const before = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) =>
			request.method === 'PATCH'
				? json(
						{ title: 'Unprocessable', status: 422, detail: "'DE00 1234' is not a valid IBAN" },
						422
					)
				: before(request)
		);
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		await user.click(
			screen.getByRole('button', { name: new RegExp(`^${m.master_identifiers()}`) })
		);
		await user.click(screen.getByRole('button', { name: m.identifier_add_short() }));
		await user.type(screen.getByLabelText(m.identifier_value()), 'DE00 1234');
		await user.click(screen.getByRole('button', { name: m.master_tab_general() }));
		await user.click(screen.getByRole('button', { name: m.save() }));
		const tab = await screen.findByRole('button', {
			name: new RegExp(`^${m.master_identifiers()}`)
		});
		await waitFor(() => expect(tab.getAttribute('aria-pressed')).toBe('true'));
		expect(tab.textContent).toContain(m.editor_tab_problem());
		const value = screen.getByLabelText(m.identifier_value());
		expect(value.getAttribute('aria-invalid')).toBe('true');
		expect(
			screen.getAllByRole('alert').some((alert) => alert.textContent?.includes('not a valid IBAN'))
		).toBe(true);
	});

	it('has none for a tag', async () => {
		render(WithDialogs);
		masterDataDialogs.open('tags', TAGS[2] as Item);
		expect(await screen.findByDisplayValue('Dental')).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.master_tab_general() })).toBeNull();
	});
});

describe('a contact’s spellings', () => {
	it('are chips, sent as a list', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		const spellings = screen.getByRole('group', { name: m.master_aliases() });
		await user.click(within(spellings).getByRole('button', { name: m.alias_add() }));
		await user.type(within(spellings).getByLabelText(m.alias_input()), 'Nord KV{Enter}');
		await user.click(screen.getByRole('button', { name: m.save() }));
		const patch = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'PATCH');
		expect((await patch!.json()).aliases).toEqual(['Nord KV']);
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
		// The identifiers have a tab of their own.
		const openTab = (name: string) =>
			userEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }));
		await openTab(m.master_identifiers());
		// Each identifier is a line that opens.
		await userEvent.click(screen.getByRole('button', { name: /^4711/ }));
		let topic = screen.getByLabelText(m.identifier_topic());
		expect(selectedValue(topic)).toBe('p1');
		expect((await optionsOf(topic)).map((option) => option.value)).toEqual(['', 'p1']);
		// Enabling another (in the picker over the dialog) offers it to the identifiers.
		await openTab(m.master_tab_general());
		const chips = screen.getByRole('group', { name: m.master_topics() });
		expect(within(chips).getByText('Arbeit')).toBeTruthy();
		await userEvent.click(within(chips).getByRole('button', { name: m.picker_add_topic_label() }));
		const picker = await pickerNamed(m.master_topics());
		await userEvent.click(within(picker).getByLabelText('Krankenversicherung'));
		await userEvent.click(within(picker).getByText(m.picker_done()));
		expect(within(chips).getByText('Krankenversicherung')).toBeTruthy();
		// Back in its tab, the line is still open.
		await openTab(m.master_identifiers());
		topic = screen.getByLabelText(m.identifier_topic());
		expect((await optionsOf(topic)).map((option) => option.value)).toEqual(['', 'p1', 'p2']);
		await choose(userEvent.setup(), topic, 'p2');
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
		await user.click(await screen.findByTitle('piggy-bank', {}, LOADED));
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

	it('puts a contact’s logo beside its name on a phone, what to do with it below', async () => {
		phone.override(true);
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		const name = await screen.findByDisplayValue('Nord Versicherungsgruppe');
		const block = name.closest('[data-logo-beside]') as HTMLElement;
		const [row, below] = [...block.children] as HTMLElement[];
		expect(row.contains(name) && row.querySelector('img')?.getAttribute('src')).toBe(FETCHED.url);
		expect(within(below).getByRole('button', { name: m.logo_upload() })).toBeTruthy();
		// Short beside the name, but named for what it fetches.
		const fetchButton = within(below).getByRole('button', { name: m.logo_fetch() });
		expect(fetchButton.textContent?.trim()).toBe(m.logo_fetch_short());
		expect(within(below).getByText(/nord\.example/, { selector: 'span' })).toBeTruthy();
		// Nothing of the logo under its own label any more.
		expect(screen.queryByText(m.logo_title())).toBeNull();
		masterDataDialogs.close();
		await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		// A new contact: its initials beside the name as it is typed.
		masterDataDialogs.open('contacts');
		await user.type(await screen.findByLabelText(m.field_name()), 'Süd Bank');
		const fresh = screen.getByLabelText(m.field_name()).closest('[data-logo-beside]')!;
		expect(fresh.querySelector('[data-initials]')?.textContent?.trim()).toBe('SB');
		expect(within(fresh as HTMLElement).getByText(m.logo_after_create())).toBeTruthy();
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

describe('a new tag', () => {
	it('asks for its kind first, then for what that kind has', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('any-tag');
		const kinds = await screen.findByRole('group', { name: m.tag_kind() });
		expect(within(kinds).getAllByRole('radio')).toHaveLength(4);
		expect(screen.getByText(m.tag_kind_topic_example())).toBeTruthy();
		// Nothing else before the kind.
		expect(screen.queryByLabelText(m.field_name())).toBeNull();
		expect((screen.getByRole('button', { name: m.create() }) as HTMLButtonElement).disabled).toBe(
			true
		);
		await user.click(within(kinds).getByLabelText(m.tag_kind_topic(), { exact: false }));
		const parent = screen.getByLabelText(m.topic_parent());
		expect((await optionsOf(parent)).map((option) => option.value)).toEqual(['', 'p1', 'p2']);
		expect(screen.getByText(m.tag_preview_topic())).toBeTruthy();
		// Another kind: its parents, no assignment for a group, hidden at documents.
		await user.click(within(kinds).getByLabelText(m.tag_kind_contact(), { exact: false }));
		const groups = screen.getByLabelText(m.tag_parent_group());
		expect((await optionsOf(groups)).map((option) => option.value)).toEqual(['', 'g1']);
		expect(screen.queryByLabelText(m.tag_assignment_auto())).toBeNull();
		expect((screen.getByLabelText(m.tag_shown()) as HTMLInputElement).checked).toBe(false);
		await user.type(screen.getByLabelText(m.field_name()), 'Versicherungsmakler');
		await choose(user, groups, 'g1');
		await user.click(screen.getByRole('button', { name: m.create() }));
		const post = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'POST');
		expect(new URL(post!.url).pathname).toBe('/api/v1/tags');
		expect(await post!.json()).toEqual({
			name: 'Versicherungsmakler',
			scope: 'contact',
			parent_id: 'g1',
			shown: false,
			icon: null,
			color: null
		});
	});

	it('skips the kind where it is given', async () => {
		render(WithDialogs);
		masterDataDialogs.open('topics');
		expect(await screen.findByLabelText(m.field_name())).toBeTruthy();
		expect(screen.queryByRole('group', { name: m.tag_kind() })).toBeNull();
		expect(screen.getByLabelText(m.topic_parent())).toBeTruthy();
	});
});

describe('creating from a picker', () => {
	it('makes a group with its details over the contact dialog, chosen there after', async () => {
		const user = userEvent.setup();
		const MAKLER = tag('g9', ['Makler'], null, 'contact');
		let made = false;
		const before = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) => {
			const path = new URL(request.url).pathname;
			if (path === '/api/v1/tags' && request.method === 'POST') {
				made = true;
				return json(MAKLER, 201);
			}
			if (path === '/api/v1/tags') return json(made ? [...TAGS, MAKLER] : TAGS);
			return before(request);
		});
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const picker = await pickerNamed(m.master_contact_groups());
		await user.type(within(picker).getByRole('searchbox', { hidden: true }), 'Makler');
		await user.click(within(picker).getByText(m.create_named({ name: 'Makler' })));
		// The tag dialog over the contact's: its kind set, the name filled in.
		const nested = await screen.findByRole('dialog', { name: m.master_add_contact_group() });
		expect((within(nested).getByLabelText(m.field_name()) as HTMLInputElement).value).toBe(
			'Makler'
		);
		expect(within(nested).queryByRole('group', { name: m.tag_kind() })).toBeNull();
		await user.click(within(nested).getByRole('button', { name: m.create() }));
		const post = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'POST');
		expect(await post!.json()).toMatchObject({ name: 'Makler', scope: 'contact' });
		await waitFor(() =>
			expect(
				within(screen.getByRole('group', { name: m.master_groups() })).getByText('Makler')
			).toBeTruthy()
		);
		await user.click(screen.getByRole('button', { name: m.save() }));
		const patch = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'PATCH');
		expect((await patch!.json()).group_ids).toEqual(['g9']);
	});
});

describe('creating from a search', () => {
	it('makes a contact in its dialog over the page, the name filled in, and hands it back', async () => {
		const user = userEvent.setup();
		const BAKERY = { ...CONTACT, id: 'c9', name: 'Bäckerei Korn' };
		const before = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) => {
			const path = new URL(request.url).pathname;
			if (path === '/api/v1/contacts' && request.method === 'POST') return json(BAKERY, 201);
			return before(request);
		});
		const changed = masterDataDialogs.changed;
		render(WithDialogs);
		const made = masterDataDialogs.create('contacts', 'Bäckerei Korn');
		const dialog = await screen.findByRole('dialog', { name: m.master_add_contact() });
		expect((within(dialog).getByLabelText(m.field_name()) as HTMLInputElement).value).toBe(
			'Bäckerei Korn'
		);
		await user.click(within(dialog).getByRole('button', { name: m.create() }));
		expect(await made).toMatchObject({ id: 'c9', name: 'Bäckerei Korn' });
		const post = fetchMock.mock.calls.map((call) => call[0]).find((r) => r.method === 'POST');
		expect(await post!.json()).toMatchObject({ name: 'Bäckerei Korn' });
		expect(masterDataDialogs.changed).toBe(changed + 1);
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(masterDataDialogs.nested).toEqual([]);
	});

	it('hands back nothing when the dialog closes without', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		const made = masterDataDialogs.create('document-types', 'Mahnung');
		const dialog = await screen.findByRole('dialog', { name: m.master_add_type() });
		expect(within(dialog).getByDisplayValue('Mahnung')).toBeTruthy();
		await user.keyboard('{Escape}');
		expect(await made).toBeNull();
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(fetchMock.mock.calls.some((call) => call[0].method === 'POST')).toBe(false);
	});
});

describe('a group made in a dialog that makes something', () => {
	it('stays chosen there, and what was typed stays too', async () => {
		const user = userEvent.setup();
		const MAKLER = tag('g9', ['Makler'], null, 'contact');
		let made = false;
		const before = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (request) => {
			const path = new URL(request.url).pathname;
			if (path === '/api/v1/tags' && request.method === 'POST') {
				made = true;
				return json(MAKLER, 201);
			}
			if (path === '/api/v1/tags') return json(made ? [...TAGS, MAKLER] : TAGS);
			return before(request);
		});
		render(WithDialogs);
		// A contact made from a document's search.
		void masterDataDialogs.create('contacts', 'N27');
		const dialog = await screen.findByRole('dialog', { name: m.master_add_contact() });
		const name = within(dialog).getByLabelText(m.field_name()) as HTMLInputElement;
		await user.clear(name);
		await user.type(name, 'N27 Bank');
		await user.click(within(dialog).getByRole('button', { name: m.picker_add_group_label() }));
		const picker = await pickerNamed(m.master_contact_groups());
		await user.type(within(picker).getByRole('searchbox', { hidden: true }), 'Makler');
		await user.click(within(picker).getByText(m.create_named({ name: 'Makler' })));
		const nested = await screen.findByRole('dialog', { name: m.master_add_contact_group() });
		await user.click(within(nested).getByRole('button', { name: m.create() }));
		await waitFor(() =>
			expect(
				within(screen.getByRole('group', { name: m.master_groups() })).getByText('Makler')
			).toBeTruthy()
		);
		expect((screen.getByLabelText(m.field_name()) as HTMLInputElement).value).toBe('N27 Bank');
	});
});

describe('stacked dialogs', () => {
	it('closes only the tag dialog on top with Escape', async () => {
		const user = userEvent.setup();
		render(WithDialogs);
		masterDataDialogs.open('contacts', CONTACT as unknown as Item);
		expect(await screen.findByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const picker = await pickerNamed(m.master_contact_groups());
		await user.type(within(picker).getByRole('searchbox', { hidden: true }), 'Makler');
		await user.click(within(picker).getByText(m.create_named({ name: 'Makler' })));
		const nested = await screen.findByRole('dialog', { name: m.master_add_contact_group() });
		expect(within(nested).getByDisplayValue('Makler')).toBeTruthy();
		await user.keyboard('{Escape}');
		await waitFor(() =>
			expect(screen.queryByRole('dialog', { name: m.master_add_contact_group() })).toBeNull()
		);
		expect(masterDataDialogs.nested).toEqual([]);
		expect(masterDataDialogs.request).not.toBeNull();
		expect(screen.getByDisplayValue('Nord Versicherungsgruppe')).toBeTruthy();
		const posted = fetchMock.mock.calls.some((call) => call[0].method === 'POST');
		expect(posted).toBe(false);
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
