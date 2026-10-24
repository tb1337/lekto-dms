/**
 * What the document view does with a document from more than one place: the head and the
 * filing box offer the move, the head and the form the retry.
 */
import { spaceOptions, type Lookup, type UserName } from '#lib/masterdata.svelte.ts';

/** Where the document may be moved: into a space the caller edits, or handed over into
 * another user's personal space; never where it lies. Nothing without the master data. */
export function moveTargets(
	lookup: Lookup | null,
	user: { id: string; role?: UserName['role'] } | null,
	spaceId: string
): { value: string; label: string }[] {
	if (!lookup) return [];
	return spaceOptions(lookup.spaces, lookup.users, user).filter(
		(option) => option.value !== spaceId
	);
}
