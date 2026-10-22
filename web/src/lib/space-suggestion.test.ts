import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import {
	handedTo,
	newReaders,
	onlySpace,
	suggestedSpace,
	suggestionText,
	unseenBy,
	unseenText
} from '#lib/space-suggestion.ts';

type OpenNode = components['schemas']['OpenNodeOut'];

const member = (user_id: string, username: string, role = 'edit') => ({
	user_id,
	username,
	role,
	active: true
});
const lookup = {
	contacts: [],
	documentTypes: [],
	tags: [],
	spaces: [
		{
			id: 'mine',
			name: 'Personal',
			personal_of: 'u1',
			role: 'edit',
			members: [member('u1', 'tobi')]
		},
		{
			id: 'house',
			name: 'Haushalt',
			personal_of: null,
			role: 'edit',
			members: [member('u1', 'tobi'), member('u2', 'anna', 'read'), member('u3', 'bob')]
		}
	],
	users: [
		{ id: 'u1', username: 'tobi', role: 'user', personal_space_id: 'mine' },
		{ id: 'u2', username: 'anna', role: 'user', personal_space_id: 'annas' }
	]
} as unknown as Lookup;

const node = (fields: { field: string; suggestion?: unknown; unseen_by?: string[] }[]) =>
	({ node: 'judge', outcome: 'uncertain', reason: null, fields }) as unknown as OpenNode;

describe('the suggested space', () => {
	beforeEach(() =>
		session.start({
			user: { id: 'u1', username: 'tobi', role: 'user' },
			method: 'password',
			expires_at: '2026-10-22T12:00:00Z',
			csrf_token: 'token'
		} as never)
	);
	afterEach(() => session.clear());

	it('is the first open space check with a suggestion', () => {
		expect(suggestedSpace([node([{ field: 'contact', suggestion: 'c1' }])])).toBeNull();
		expect(suggestedSpace([node([{ field: 'space', suggestion: null }])])).toBeNull();
		expect(
			suggestedSpace([
				node([{ field: 'contact' }]),
				node([{ field: 'space', suggestion: 'house' }])
			])
		).toBe('house');
		expect(onlySpace([node([{ field: 'space', suggestion: 'house' }])])).toBe(true);
		expect(onlySpace([node([{ field: 'space' }, { field: 'contact' }])])).toBe(false);
		expect(onlySpace([])).toBe(false);
		// A failed node (no fields) is the point to show, not the suggestion beside it.
		const failed = { node: 'ocr', outcome: 'failed', reason: 'broken', fields: [] };
		expect(onlySpace([failed as unknown as OpenNode, node([{ field: 'space' }])])).toBe(false);
	});

	it('does not name a space the caller cannot see', () => {
		expect(suggestionText('elsewhere', 'mine', lookup)).toBe(
			m.space_suggestion({ space: m.space_unseen() })
		);
		expect(suggestionText('elsewhere', 'mine', lookup)).not.toContain('elsewhere');
	});

	it('names who sees the document there anew', () => {
		expect(newReaders('house', 'mine', lookup)).toEqual(['anna', 'bob']);
		// Another user's personal space the caller is no member of: that user.
		expect(newReaders('annas', 'mine', lookup)).toEqual(['anna']);
		expect(newReaders('elsewhere', 'mine', lookup)).toEqual([]);
		expect(newReaders('house', 'mine', null)).toEqual([]);
	});

	it('reads as a suggestion with the new readers', () => {
		expect(suggestionText('house', 'mine', lookup)).toBe(
			m.space_suggestion_for({ space: 'Haushalt', names: 'anna, bob' })
		);
		expect(suggestionText('mine', 'house', lookup)).toBe(
			m.space_suggestion({ space: m.space_personal() })
		);
	});

	it('reads a suggested personal space of another user as a hand-over', () => {
		expect(handedTo('annas', 'mine', lookup)).toBe('anna');
		expect(suggestionText('annas', 'mine', lookup)).toBe(
			m.space_suggestion_hand_over({ name: 'anna' })
		);
		// Anna reads Haushalt already: her personal space is no hand-over from there.
		expect(handedTo('annas', 'house', lookup)).toBeNull();
		expect(handedTo('house', 'mine', lookup)).toBeNull();
	});

	it('names those the document names who would not see it there', () => {
		const open = [node([{ field: 'space', suggestion: null, unseen_by: ['u2', 'u9'] }])];
		expect(unseenBy(open)).toEqual(['u2', 'u9']);
		expect(unseenBy([node([{ field: 'space' }])])).toEqual([]);
		expect(unseenText(['u2'], lookup)).toBe(m.space_named_unseen({ names: 'anna' }));
		// Someone the caller cannot tell stays unnamed.
		expect(unseenText(['u2', 'u9'], lookup)).toBe(
			m.space_named_unseen({ names: `anna, ${m.space_named_someone()}` })
		);
		expect(unseenText([], lookup)).toBe('');
	});
});
