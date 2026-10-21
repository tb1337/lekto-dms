import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
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
	role: 'edit',
	members: [],
	created_at: '2026-10-21T08:00:00Z',
	version: 1,
	...changes
});

const HOUSE = space('house', {
	name: 'Haushalt',
	members: [
		{ user_id: 'u1', role: 'edit' },
		{ user_id: 'u2', role: 'read' }
	]
});
const TOBI = space('tobi', { personal_of: 'u1', members: [{ user_id: 'u1', role: 'edit' }] });
const ANNA = space('anna', {
	personal_of: 'u2',
	role: 'read',
	members: [
		{ user_id: 'u2', role: 'edit' },
		{ user_id: 'u1', role: 'read' }
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
		'DELETE /api/v1/spaces/house/members/u2': () => HOUSE
	});
	vi.stubGlobal('fetch', api);
	render(Page);
	return api;
}

beforeEach(() => signIn('u1'));
afterEach(() => {
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
		// Not renamed nor deleted: a personal space; a space one only reads.
		expect(screen.queryByRole('button', { name: m.space_delete({ name: 'Personal' }) })).toBeNull();
		expect(screen.getByRole('button', { name: m.space_delete({ name: 'Haushalt' }) })).toBeTruthy();
		// Members: of one's own personal space and of a space one edits, not of another's.
		expect(
			screen.getByRole('button', { name: m.space_members({ name: m.space_personal() }) })
		).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.space_members({ name: 'anna' }) })).toBeNull();
	});

	it('shows an admin the spaces they are no member of apart', async () => {
		signIn('u3', 'admin');
		const admins = space('admins', {
			personal_of: 'u3',
			members: [{ user_id: 'u3', role: 'edit' }]
		});
		start([HOUSE, TOBI, admins]);
		const others = await screen.findByRole('region', { name: m.spaces_others() });
		expect(within(others).getAllByRole('listitem')).toHaveLength(2);
		// An admin chooses the members of another user's personal space.
		expect(
			within(others).getByRole('button', { name: m.space_members({ name: 'tobi' }) })
		).toBeTruthy();
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
		await waitFor(() => expect(calls(api)).toContain('DELETE /api/v1/spaces/house/members/u2'));
		await choose(user, within(dialog).getByLabelText(m.members_add()), 'u3');
		await user.click(within(dialog).getByRole('button', { name: m.members_grant() }));
		await waitFor(() => expect(calls(api)).toContain('PUT /api/v1/spaces/house/members/u3'));
		const put = api.mock.calls.find(([request]) => request.method === 'PUT')![0];
		expect(await put.json()).toEqual({ role: 'read' });
	});
});
