import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import {
	foreignSpace,
	spaceLabel,
	spaceOptions,
	userLabel,
	userName,
	type Space
} from './masterdata.svelte.ts';

const users = [
	{ id: 'u1', username: 'tobi', role: 'user' as const, personal_space_id: 'mine' },
	{ id: 'u2', username: 'anna', role: 'user' as const, personal_space_id: 'anna' },
	{ id: 'u3', username: 'bob', role: 'user' as const, personal_space_id: 'bobs' }
];
const space = (id: string, changes: Partial<Space> = {}): Space => ({
	id,
	name: 'Personal',
	personal_of: null,
	description: null,
	role: 'edit',
	members: [{ user_id: 'u1', role: 'edit', username: 'tobi', active: true }],
	created_at: '2026-10-21T08:00:00Z',
	version: 1,
	...changes
});

const mine = space('mine', { personal_of: 'u1' });
const house = space('house', { name: 'Haushalt' });
const anna = space('anna', {
	personal_of: 'u2',
	role: 'read',
	members: [
		{ user_id: 'u2', role: 'edit', username: 'anna', active: true },
		{ user_id: 'u1', role: 'read', username: 'tobi', active: true }
	]
});

describe('spaces by name', () => {
	it('names a personal space "Personal" for its user and by the user for others', () => {
		expect(spaceLabel(mine, users, 'u1')).toBe(m.space_personal());
		expect(spaceLabel(mine, users, 'u2')).toBe('tobi');
		expect(spaceLabel(house, users, 'u1')).toBe('Haushalt');
	});

	it('names a space only where the caller is no member (an admin looking at others)', () => {
		const lookup = { spaces: [mine, house, anna], users };
		expect(foreignSpace('house', lookup, 'u1')).toBeNull();
		expect(foreignSpace('house', lookup, 'u3')).toBe('Haushalt');
		expect(foreignSpace('mine', lookup, 'u3')).toBe('tobi');
		expect(foreignSpace('gone', lookup, 'u3')).toBeNull();
	});

	it('offers the edited spaces, then hand-overs to every other user', () => {
		// bob's personal space is not listed for tobi; a hand-over needs no membership.
		expect(spaceOptions([mine, house, anna], users, users[0])).toEqual([
			{ value: 'mine', label: m.space_personal() },
			{ value: 'house', label: 'Haushalt' },
			{ value: 'anna', label: m.move_hand_over({ name: 'anna' }) },
			{ value: 'bobs', label: m.move_hand_over({ name: 'bob' }) }
		]);
	});
});

describe('the names of users', () => {
	it('shows the display name, else the username', () => {
		const named = { id: 'u4', username: 'carla', display_name: 'Carla Example' };
		expect(userLabel(named)).toBe('Carla Example');
		expect(userLabel({ username: 'carla', display_name: null })).toBe('carla');
		expect(userName([...users, named], 'u4')).toBe('Carla Example');
		expect(userName(users, 'nobody')).toBe('nobody');
		expect(spaceLabel({ name: 'Personal', personal_of: 'u4' }, [named], 'u1')).toBe(
			'Carla Example'
		);
	});
});
