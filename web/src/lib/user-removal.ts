/**
 * Deleting a user who leaves spaces behind (Tobi, 22.10.2026): the API names the spaces that
 * stop it (`GET /users/{id}/removal`); the admin decides for each in the dialog, all in one
 * request: an empty space goes along, documents move into another space, or another user
 * edits the space from then on.
 */
import type { components } from '#lib/api/schema.ts';
import { spaceLabel } from '#lib/masterdata.svelte.ts';

type Space = components['schemas']['SpaceOut'];
type User = components['schemas']['UserOut'];
export type BlockingSpace = components['schemas']['BlockingSpaceOut'];
export type Settlement = components['schemas']['SpaceSettlementIn'];

export type How = 'remove' | 'move_to' | 'editor';

/** What the admin chose for a space: how, and the space or user it needs (empty: none yet). */
export interface Decision {
	how: How;
	target: string;
}

const HOWS: readonly How[] = ['remove', 'move_to', 'editor'];

export function choicesOf(space: BlockingSpace): How[] {
	return HOWS.filter((how) => space.choices.includes(how));
}

/** The first choice of each space, nothing picked yet. */
export function initialDecisions(spaces: readonly BlockingSpace[]): Record<string, Decision> {
	return Object.fromEntries(
		spaces.map((space) => [space.space_id, { how: choicesOf(space)[0] ?? 'move_to', target: '' }])
	);
}

/** Whether every space has a decision it allows, with its space or user picked. */
export function settled(
	spaces: readonly BlockingSpace[],
	decisions: Record<string, Decision>
): boolean {
	return spaces.every((space) => {
		const decision = decisions[space.space_id];
		return (
			decision !== undefined &&
			space.choices.includes(decision.how) &&
			(decision.how === 'remove' || decision.target !== '')
		);
	});
}

export function removalBody(
	spaces: readonly BlockingSpace[],
	decisions: Record<string, Decision>
): { spaces: Settlement[] } {
	return {
		spaces: spaces.map((space) => {
			const { how, target } = decisions[space.space_id] ?? { how: 'remove', target: '' };
			if (how === 'move_to') return { space_id: space.space_id, remove: false, move_to: target };
			if (how === 'editor') return { space_id: space.space_id, remove: false, editor: target };
			return { space_id: space.space_id, remove: true };
		})
	};
}

/** Where the documents of `leaving`'s spaces may go: a space that stays, and no deactivated
 * user's personal space (as a move by hand). */
export function moveTargets(
	spaces: readonly Space[],
	users: readonly User[],
	leaving: string,
	blocking: readonly BlockingSpace[],
	me: string | undefined
): { value: string; label: string }[] {
	const gone = new Set(blocking.map((space) => space.space_id));
	const inactive = new Set(users.filter((user) => user.active === false).map((user) => user.id));
	return spaces
		.filter(
			(space) =>
				!gone.has(space.id) &&
				space.personal_of !== leaving &&
				!(space.personal_of !== null && inactive.has(space.personal_of))
		)
		.map((space) => ({ value: space.id, label: spaceLabel(space, users, me) }))
		.toSorted((a, b) => a.label.localeCompare(b.label));
}

/** Who may edit a space of `leaving` from then on: the other active users. */
export function editorOptions(
	users: readonly User[],
	leaving: string
): { value: string; label: string }[] {
	return users
		.filter((user) => user.id !== leaving && user.active !== false)
		.map((user) => ({ value: user.id, label: user.username }));
}
