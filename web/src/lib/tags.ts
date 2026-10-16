/**
 * Tags as trees, as the API lists them (`GET /tags`: each after its parent, siblings by name,
 * with its path): the tags of a scope, their paths, the tree of a master data tab, and what a
 * search matches. Documents show the leaf; the path says where it stands.
 */
import type { Tag, TagScope } from '#lib/masterdata.svelte.ts';

export const SEPARATOR = ' › ';

/** What the helpers need of a tag. */
export type TagLike = Pick<Tag, 'id' | 'name' | 'scope' | 'parent_id' | 'path'>;

/** "Insurance › Health". */
export function pathLabel(tag: Pick<Tag, 'name' | 'path'>): string {
	return (tag.path.length > 0 ? tag.path : [tag.name]).join(SEPARATOR);
}

/** The tags of `scope`, in the order of the tree. */
export function ofScope<T extends TagLike>(tags: readonly T[], scope: TagScope): T[] {
	return tags.filter((tag) => tag.scope === scope);
}

/** Options of a picker: the tags of `scope` labelled with their path. */
export function tagOptions(
	tags: readonly TagLike[],
	scope: TagScope
): { value: string; label: string }[] {
	return ofScope(tags, scope).map((tag) => ({ value: tag.id, label: pathLabel(tag) }));
}

/** Whether every word of `query` stands in the tag's path: a search for a parent's name finds
 * the tags below it. */
export function matchesQuery(tag: Pick<Tag, 'name' | 'path'>, query: string): boolean {
	const path = pathLabel(tag).toLocaleLowerCase();
	return query
		.toLocaleLowerCase()
		.split(/\s+/)
		.filter((word) => word !== '')
		.every((word) => path.includes(word));
}

/** The ids of the tags below `id` (not `id` itself). */
export function below(tags: readonly TagLike[], id: string): Set<string> {
	const found = new Set<string>();
	let added = true;
	while (added) {
		added = false;
		for (const tag of tags) {
			if (
				tag.parent_id &&
				(tag.parent_id === id || found.has(tag.parent_id)) &&
				!found.has(tag.id)
			) {
				found.add(tag.id);
				added = true;
			}
		}
	}
	return found;
}

/** The tags of a tree by their parent (null: the top), in the order of the list. */
export function childrenOf<T extends TagLike>(tags: readonly T[]): Map<string | null, T[]> {
	const ids = new Set(tags.map((tag) => tag.id));
	const children = new Map<string | null, T[]>();
	for (const tag of tags) {
		const parent = tag.parent_id && ids.has(tag.parent_id) ? tag.parent_id : null;
		children.set(parent, [...(children.get(parent) ?? []), tag]);
	}
	return children;
}

/** The rows of a tree view: each tag with its depth, below a collapsed tag nothing. */
export function visibleRows<T extends TagLike>(
	tags: readonly T[],
	collapsed: ReadonlySet<string>
): { tag: T; depth: number; hasChildren: boolean }[] {
	const children = childrenOf(tags);
	const rows: { tag: T; depth: number; hasChildren: boolean }[] = [];
	const seen = new Set<string>();
	const walk = (parent: string | null, depth: number) => {
		for (const tag of children.get(parent) ?? []) {
			if (seen.has(tag.id)) continue;
			seen.add(tag.id);
			const kids = children.get(tag.id) ?? [];
			rows.push({ tag, depth, hasChildren: kids.length > 0 });
			if (!collapsed.has(tag.id)) walk(tag.id, depth + 1);
		}
	};
	walk(null, 0);
	return rows;
}
