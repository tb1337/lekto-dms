import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { scope } from '#lib/scope.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi } from '#lib/testing/documents.ts';
import { choose } from '#lib/testing/select.ts';
import Page from './+page.svelte';

type Space = components['schemas']['SpaceOut'];
type User = components['schemas']['UserOut'];

const USERS: User[] = [
	{ id: 'u1', username: 'tobi', role: 'user', active: true },
	{ id: 'u2', username: 'anna', role: 'user', active: true },
	{ id: 'u3', username: 'admin', role: 'admin', active: true }
] as User[];

const space = (id: string, changes: Partial<Space>): Space => ({
	id,
	name: 'Personal',
	personal_of: null,
	description: null,
	role: 'edit',
	members: [],
	created_at: '2026-10-21T08:00:00Z',
	version: 1,
	...changes
});

const HOUSE = space('house', {
	name: 'Haushalt',
	members: [
		{ user_id: 'u1', role: 'edit', username: 'tobi', active: true },
		{ user_id: 'u2', role: 'read', username: 'anna', active: true }
	]
});
const TOBI = space('tobi', {
	personal_of: 'u1',
	members: [{ user_id: 'u1', role: 'edit', username: 'tobi', active: true }]
});
const ANNA = space('anna', {
	personal_of: 'u2',
	role: 'read',
	members: [
		{ user_id: 'u2', role: 'edit', username: 'anna', active: true },
		{ user_id: 'u1', role: 'read', username: 'tobi', active: true }
	]
});

function signIn(id: string, role: User['role'] = 'user') {
	session.start({
		user: { id, username: USERS.find((user) => user.id === id)?.username ?? id, role },
		method: 'password',
		expires_at: '2026-10-21T12:00:00Z',
		csrf_token: 'token'
	} as never);
}

function start(spaces: Space[]) {
	const api = fakeApi({
		'GET /api/v1/spaces': () => spaces,
		'GET /api/v1/users': () => USERS,
		'PUT /api/v1/spaces/house/members/u3': () => HOUSE,
		'DELETE /api/v1/spaces/house/members/u2': () => HOUSE,
		'POST /api/v1/spaces': () => HOUSE,
		'PATCH /api/v1/spaces/house': () => HOUSE,
		'PATCH /api/v1/spaces/tobi': () => TOBI
	});
	vi.stubGlobal('fetch', api);
	render(Page);
	return api;
}

beforeEach(() => signIn('u1'));
afterEach(() => {
	scope.set(false);
	vi.unstubAllGlobals();
	session.clear();
});

describe('spaces', () => {
	it('lists the personal space first, then the others with members and role', async () => {
		start([HOUSE, ANNA, TOBI]);
		const own = await screen.findByRole('region', { name: m.spaces_own() });
		const rows = within(own).getAllByRole('listitem');
		expect(rows.map((row) => row.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			`${m.space_personal()} ${m.space_only_you()}`,
			`Haushalt ${m.space_members_line({ names: m.space_member_reads({ name: 'anna' }) })}`,
			`anna ${m.space_personal()} ${m.space_role_read()} ${m.space_members_line({ names: 'anna' })}`
		]);
		expect(screen.queryByRole('region', { name: m.spaces_others() })).toBeNull();
		// Deleted in the editor, not in the row (web/DESIGN.md, "Lists").
		expect(screen.queryByRole('button', { name: m.space_delete({ name: 'Haushalt' }) })).toBeNull();
		// Members: of one's own personal space and of a space one edits, not of another's.
		expect(
			screen.getByRole('button', { name: m.space_members({ name: m.space_personal() }) })
		).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.space_members({ name: 'anna' }) })).toBeNull();
	});

	it('shows an admin the spaces they are no member of apart, with all users included', async () => {
		signIn('u3', 'admin');
		scope.set(true);
		const admins = space('admins', {
			personal_of: 'u3',
			members: [{ user_id: 'u3', role: 'edit', username: 'admin', active: true }]
		});
		const api = start([HOUSE, TOBI, admins]);
		const others = await screen.findByRole('region', { name: m.spaces_others() });
		expect(within(others).getAllByRole('listitem')).toHaveLength(2);
		const lists = calls(api).filter((call) => call.startsWith('GET /api/v1/spaces'));
		expect(lists.at(-1)).toContain('all_users=true');
		// An admin chooses the members of another user's personal space.
		expect(
			within(others).getByRole('button', { name: m.space_members({ name: 'tobi' }) })
		).toBeTruthy();
	});

	it('shows an admin only their own spaces without all users, like everyone', async () => {
		signIn('u3', 'admin');
		const admins = space('admins', {
			personal_of: 'u3',
			members: [{ user_id: 'u3', role: 'edit', username: 'admin', active: true }]
		});
		const api = start([admins]);
		await screen.findByRole('heading', { name: m.spaces_own() });
		expect(screen.queryByRole('region', { name: m.spaces_others() })).toBeNull();
		const lists = calls(api).filter((call) => call.startsWith('GET /api/v1/spaces'));
		expect(lists.at(-1)).not.toContain('all_users');
	});

	it('adds and removes members; the last editor stays', async () => {
		signIn('u1');
		const user = userEvent.setup();
		const api = start([HOUSE, TOBI]);
		await user.click(
			await screen.findByRole('button', { name: m.space_members({ name: 'Haushalt' }) })
		);
		const dialog = await screen.findByRole('dialog');
		// tobi is the only editor: no role to change, nothing to remove.
		expect(
			within(dialog).queryByRole('button', { name: m.members_remove({ name: 'tobi' }) })
		).toBeNull();
		await user.click(
			within(dialog).getByRole('button', { name: m.members_remove({ name: 'anna' }) })
		);
		// Asked first.
		const ask = await screen.findByRole('alertdialog');
		await user.click(within(ask).getByRole('button', { name: m.members_remove_do() }));
		await waitFor(() => expect(calls(api)).toContain('DELETE /api/v1/spaces/house/members/u2'));
		await choose(user, within(dialog).getByLabelText(m.members_add()), 'u3');
		await user.click(within(dialog).getByRole('button', { name: m.members_grant() }));
		await waitFor(() => expect(calls(api)).toContain('PUT /api/v1/spaces/house/members/u3'));
		const put = api.mock.calls.find(([request]) => request.method === 'PUT')![0];
		expect(await put.json()).toEqual({ role: 'read' });
	});
	it('shows what belongs in a space, and creates one with its description', async () => {
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const api = start([{ ...HOUSE, description: 'Wohnung, Nebenkosten' }, TOBI]);
		expect(await screen.findByText('Wohnung, Nebenkosten')).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.space_new() }));
		const dialog = await screen.findByRole('dialog');
		await user.type(within(dialog).getByLabelText(m.field_name()), 'Auto');
		await user.type(
			within(dialog).getByLabelText(m.space_description()),
			'Versicherung, Werkstatt'
		);
		await user.click(within(dialog).getByRole('button', { name: m.create() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/spaces'));
		const post = api.mock.calls.find(([request]) => request.method === 'POST')![0];
		expect(await post.json()).toEqual({ name: 'Auto', description: 'Versicherung, Werkstatt' });
	});

	it('describes the personal space without renaming it', async () => {
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const api = start([HOUSE, TOBI]);
		await user.click(
			await screen.findByRole('button', { name: m.space_edit({ name: m.space_personal() }) })
		);
		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).queryByLabelText(m.field_name())).toBeNull();
		await user.type(within(dialog).getByLabelText(m.space_description()), 'Arbeit');
		await user.click(within(dialog).getByRole('button', { name: m.save() }));
		await waitFor(() => expect(calls(api)).toContain('PATCH /api/v1/spaces/tobi'));
		const patch = api.mock.calls.find(([request]) => request.method === 'PATCH')![0];
		expect(await patch.json()).toEqual({ description: 'Arbeit' });
	});

	it('renames a shared space with its description, and removes an emptied one', async () => {
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const api = start([{ ...HOUSE, description: 'alt' }, TOBI]);
		await user.click(
			await screen.findByRole('button', { name: m.space_edit({ name: 'Haushalt' }) })
		);
		const dialog = await screen.findByRole('dialog');
		const name = within(dialog).getByLabelText(m.field_name());
		await user.clear(name);
		await user.type(name, 'Zuhause');
		await user.clear(within(dialog).getByLabelText(m.space_description()));
		await user.click(within(dialog).getByRole('button', { name: m.save() }));
		await waitFor(() => expect(calls(api)).toContain('PATCH /api/v1/spaces/house'));
		const patch = api.mock.calls.find(([request]) => request.method === 'PATCH')![0];
		expect(await patch.json()).toEqual({ name: 'Zuhause', description: null });
	});

	it('lets a reader leave a space, after asking', async () => {
		signIn('u2');
		// A dialog of an earlier test may still leave the body without pointer events.
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const api = start([{ ...HOUSE, role: 'read' }, ANNA]);
		// Not their own personal space.
		expect(
			screen.queryByRole('button', { name: m.space_leave({ name: m.space_personal() }) })
		).toBeNull();
		await user.click(
			await screen.findByRole('button', { name: m.space_leave({ name: 'Haushalt' }) })
		);
		const dialog = await screen.findByRole('alertdialog');
		await user.click(within(dialog).getByRole('button', { name: m.space_leave_action() }));
		await waitFor(() => expect(calls(api)).toContain('DELETE /api/v1/spaces/house/members/u2'));
	});

	it('keeps a deactivated member without a role to change, for removing', async () => {
		const user = userEvent.setup({ pointerEventsCheck: 0 });
		const gone = {
			...HOUSE,
			members: [
				{ user_id: 'u1', role: 'edit' as const, username: 'tobi', active: true },
				{ user_id: 'u9', role: 'read' as const, username: 'otto', active: false }
			]
		};
		start([gone, TOBI]);
		await user.click(
			await screen.findByRole('button', { name: m.space_members({ name: 'Haushalt' }) })
		);
		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByText(m.user_inactive())).toBeTruthy();
		expect(within(dialog).queryByLabelText(m.members_role_of({ name: 'otto' }))).toBeNull();
		expect(
			within(dialog).getByRole('button', { name: m.members_remove({ name: 'otto' }) })
		).toBeTruthy();
	});
});
