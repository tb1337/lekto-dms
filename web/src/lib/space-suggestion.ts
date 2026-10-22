/**
 * The space Lekto suggests for a document (the judge's open `space` check): which one, its
 * name, and who sees the document there that does not see it now.
 */
import type { components } from '#lib/api/schema.ts';
import { describeValue } from '#lib/describe.ts';
import { userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

type OpenNode = components['schemas']['OpenNodeOut'];

/** The suggested space of the open fields: the first open `space` check with a suggestion. */
export function suggestedSpace(open: readonly OpenNode[]): string | null {
	for (const node of open) {
		for (const check of node.fields) {
			if (check.field === 'space' && typeof check.suggestion === 'string') return check.suggestion;
		}
	}
	return null;
}

/** Whether the only open point is the suggested space (a failed node is one, without fields). */
export function onlySpace(open: readonly OpenNode[]): boolean {
	if (open.some((node) => node.outcome === 'failed')) return false;
	const fields = open.flatMap((node) => node.fields);
	return fields.length > 0 && fields.every((check) => check.field === 'space');
}

/** Whether the caller can tell which space `target` is: one of theirs, or a user's personal one. */
export function knownSpace(target: string, lookup: Lookup | null): boolean {
	if (!lookup) return false;
	return (
		lookup.spaces.some((space) => space.id === target) ||
		lookup.users.some((user) => user.personal_space_id === target)
	);
}

/** The members of `target` who are no members of `current`, by name; for another user's
 * personal space the caller is no member of, that user. Empty where the caller cannot tell. */
export function newReaders(target: string, current: string, lookup: Lookup | null): string[] {
	if (!lookup) return [];
	const there = lookup.spaces.find((space) => space.id === target);
	const here = lookup.spaces.find((space) => space.id === current);
	const already = new Set(here?.members.map((member) => member.user_id) ?? []);
	if (there) {
		return there.members
			.filter((member) => !already.has(member.user_id))
			.map((member) => userLabel(member));
	}
	const holder = lookup.users.find((user) => user.personal_space_id === target);
	return holder && !already.has(holder.id) ? [userLabel(holder)] : [];
}

/** "Vorschlag: Haushalt (sichtbar für anna)": the suggested space and who sees it there anew;
 * a space the caller cannot see is not named (its id says nothing to them). */
export function suggestionText(target: string, current: string, lookup: Lookup | null): string {
	if (!knownSpace(target, lookup)) return m.space_suggestion({ space: m.space_unseen() });
	const space = describeValue(target, lookup);
	const names = newReaders(target, current, lookup);
	return names.length > 0
		? m.space_suggestion_for({ space, names: names.join(', ') })
		: m.space_suggestion({ space });
}
