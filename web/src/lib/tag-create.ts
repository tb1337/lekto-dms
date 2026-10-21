/**
 * Creating a tag where tags are picked, for admins: a picker's search that finds no tag of its
 * kind named so offers "„…“ anlegen …", the tag dialog over the current one with the kind set
 * and the name filled in (Tobi, 20.10.2026: no making at once by the name alone). The tag it
 * makes is picked; the lists and lookups showing master data load again.
 */
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';
import { ofScope } from '#lib/tags.ts';

/** Whether a picker's `query` may become a new tag of `scope`: something typed that no tag of
 * the kind is named already (regardless of case and surrounding spaces). */
export function creatable(tags: readonly Tag[], scope: TagScope, query: string): boolean {
	const name = query.trim().toLocaleLowerCase();
	return (
		name !== '' && !ofScope(tags, scope).some((tag) => tag.name.trim().toLocaleLowerCase() === name)
	);
}

/** The tag dialog over the current one for a tag of `scope`, named `name` to start with: the
 * tag made, or null. */
export function createWithDetails(scope: TagScope, name: string): Promise<Tag | null> {
	return masterDataDialogs.createTag(scope, name.trim());
}
