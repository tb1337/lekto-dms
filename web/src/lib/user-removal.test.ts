import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import {
	editorOptions,
	initialDecisions,
	moveTargets,
	removalBody,
	settled,
	type BlockingSpace
} from '#lib/user-removal.ts';

type Space = components['schemas']['SpaceOut'];

const ANNA = 'anna-id';
const TOBI = 'tobi-id';
const GONE = 'gone-id';
const users = [
	{ id: ANNA, username: 'anna', active: true },
	{ id: TOBI, username: 'tobi', active: true },
	{ id: GONE, username: 'gone', active: false }
];

function space(id: string, name: string, personal_of: string | null = null): Space {
	return {
		id,
		name,
		personal_of,
		description: null,
		role: 'edit',
		members: [],
		created_at: '2026-10-22T00:00:00Z',
		version: 1
	} as unknown as Space;
}

const personal: BlockingSpace = {
	space_id: 'annas',
	name: 'Personal',
	personal: true,
	documents: 3,
	choices: ['move_to']
};
const household: BlockingSpace = {
	space_id: 'household',
	name: 'Household',
	personal: false,
	documents: 1,
	choices: ['move_to', 'editor']
};
const empty: BlockingSpace = {
	space_id: 'empty',
	name: 'Empty',
	personal: false,
	documents: 0,
	choices: ['remove', 'editor']
};

describe('deleting a user who leaves spaces behind', () => {
	it('starts at the first choice and waits for every target', () => {
		const spaces = [personal, household, empty];
		const decisions = initialDecisions(spaces);
		expect(decisions).toEqual({
			annas: { how: 'move_to', target: '' },
			household: { how: 'move_to', target: '' },
			empty: { how: 'remove', target: '' }
		});
		expect(settled(spaces, decisions)).toBe(false);
		decisions.annas.target = 'tobis';
		decisions.household = { how: 'editor', target: TOBI };
		expect(settled(spaces, decisions)).toBe(true);
		expect(removalBody(spaces, decisions)).toEqual({
			spaces: [
				{ space_id: 'annas', remove: false, move_to: 'tobis' },
				{ space_id: 'household', remove: false, editor: TOBI },
				{ space_id: 'empty', remove: true }
			]
		});
		expect(settled([personal], { annas: { how: 'remove', target: '' } })).toBe(false);
	});

	it('moves only into spaces that stay, never to a deactivated user', () => {
		const spaces = [
			space('annas', 'Personal', ANNA),
			space('household', 'Household'),
			space('tobis', 'Personal', TOBI),
			space('gones', 'Personal', GONE),
			space('archive', 'Archive')
		];
		const targets = moveTargets(spaces, users, ANNA, [personal, household], 'admin-id');
		expect(targets.map((target) => target.value)).toEqual(['archive', 'tobis']);
		expect(editorOptions(users, ANNA)).toEqual([{ value: TOBI, label: 'tobi' }]);
	});
});
