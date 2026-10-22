import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { moves, placeOf, rulePlaces } from '#lib/rules/places.ts';
import { GLOBAL } from '#lib/rules/save.ts';

type Space = components['schemas']['SpaceOut'];

const ME = 'me-id';

function space(id: string, name: string, role: 'read' | 'edit', personal_of: string | null = null) {
	return { id, name, role, personal_of, members: [] } as unknown as Space;
}

describe('where a rule belongs', () => {
	it('offers global to admins, the spaces one edits, the own personal first', () => {
		const spaces = [
			space('household', 'Household', 'edit'),
			space('mine', 'Personal', 'edit', ME),
			space('read', 'Read only', 'read')
		];
		expect(rulePlaces(spaces, [], ME, false).map((place) => place.value)).toEqual([
			'mine',
			'household'
		]);
		expect(rulePlaces(spaces, [], ME, true).map((place) => place.value)).toEqual([
			GLOBAL,
			'mine',
			'household'
		]);
		// Where the rule is stays among them, even a space one does not edit.
		expect(rulePlaces(spaces, [], ME, false, 'read')[0]?.value).toBe('read');
	});

	it('finds the versions that moved the rule', () => {
		const versions = [
			{ version: 3, scope: 'global' as const, space_id: null },
			{ version: 1, scope: 'space' as const, space_id: 'a' },
			{ version: 2, scope: 'space' as const, space_id: 'a' },
			{ version: 4, scope: 'space' as const, space_id: 'b' }
		];
		expect([...moves(versions)]).toEqual([
			[3, ['a', GLOBAL]],
			[4, [GLOBAL, 'b']]
		]);
		expect(placeOf({ scope: 'space', space_id: 'b' })).toBe('b');
	});
});
