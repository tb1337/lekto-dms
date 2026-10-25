/**
 * Where a rule belongs: global, or the id of its space (`GLOBAL` or a space id), the places a
 * person may choose for it, and where its versions moved it (Tobi, 22.10.2026: a rule's
 * space is changed with its content).
 */
import type { components } from '#lib/api/schema.ts';
import { spaceLabel } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { ruleSpaces } from '#lib/permissions.ts';
import { GLOBAL } from '#lib/rules/save.ts';

type Space = components['schemas']['SpaceOut'];
type User = components['schemas']['UserOut'];

export interface Placed {
	scope: 'global' | 'space';
	space_id?: string | null;
}

export function placeOf(rule: Placed): string {
	return rule.scope === 'global' ? GLOBAL : (rule.space_id ?? '');
}

/** The name of a place: `global` for a global rule (the long wording of the choice unless a
 * badge wants the short one), the space's name, "unknown" for a space the list lacks. */
export function placeLabel(
	place: string,
	spaces: readonly Space[],
	users: readonly User[],
	me: string | undefined,
	global: () => string = m.rule_scope_global
): string {
	if (place === GLOBAL) return global();
	const space = spaces.find((entry) => entry.id === place);
	return space ? spaceLabel(space, users, me) : m.rule_unknown();
}

/** The places a rule may belong to: global for admins, then the spaces the person edits, their
 * personal space first; `current`, where the rule is, always among them. */
export function rulePlaces(
	spaces: readonly Space[],
	users: readonly User[],
	me: string | undefined,
	admin: boolean,
	current?: string
): { value: string; label: string }[] {
	const places = [
		...(admin ? [{ value: GLOBAL, label: m.rule_scope_global() }] : []),
		...ruleSpaces(spaces)
			.toSorted((a, b) => Number(b.personal_of === me) - Number(a.personal_of === me))
			.map((space) => ({ value: space.id, label: spaceLabel(space, users, me) }))
	];
	if (current && !places.some((place) => place.value === current)) {
		places.unshift({ value: current, label: placeLabel(current, spaces, users, me) });
	}
	return places;
}

/** Of versions in any order, the moves: by version number, where it came from and went to. */
export function moves(
	versions: readonly (Placed & { version: number })[]
): Map<number, [string, string]> {
	const ordered = versions.toSorted((a, b) => a.version - b.version);
	const found = new Map<number, [string, string]>();
	for (const [index, version] of ordered.entries()) {
		const before = ordered[index - 1];
		if (before && placeOf(before) !== placeOf(version)) {
			found.set(version.version, [placeOf(before), placeOf(version)]);
		}
	}
	return found;
}
