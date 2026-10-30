/**
 * The values behind the references of the `fact` filter (`/identifiers/refs`): an address names
 * a fact's value only by its reference (web/DESIGN.md, "No plain data in addresses"). What the
 * page learns along the way (a lens, an open identifier, a value typed into the filter) it keeps
 * for the labels; a reference it has not met (after F5, a remembered filter) it asks the API
 * about, once.
 */
import { SvelteMap } from 'svelte/reactivity';
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { IdentifierKind } from '#lib/identifiers.ts';

const values = new SvelteMap<string, string>();
// Asked once per page, answered or not: not reactive, so a label may ask while it renders.
// eslint-disable-next-line svelte/prefer-svelte-reactivity
const asked = new Set<string>();

const key = (kind: IdentifierKind, ref: string) => `${kind}:${ref}`;

/** What `ref` names, learned from an answer that carries both. */
export function rememberRef(kind: IdentifierKind, ref: string, value: string): void {
	values.set(key(kind, ref), value);
}

/** The value of `ref`, or null while the API has not told it (then it asks). */
export function refValue(kind: IdentifierKind, ref: string): string | null {
	const known = values.get(key(kind, ref));
	if (known === undefined && !asked.has(key(kind, ref))) {
		asked.add(key(kind, ref));
		void ask(kind, ref);
	}
	return known ?? null;
}

async function ask(kind: IdentifierKind, ref: string): Promise<void> {
	try {
		const found = await unwrap(
			api.GET('/api/v1/identifiers/refs/{kind}/{ref}', { params: { path: { kind, ref } } })
		);
		values.set(key(kind, ref), found.value);
	} catch {
		// A reference of another instance or a damaged one: the label names the kind only.
	}
}

/** The reference to `value` as written (normalised by the API); throws for a value that is
 * none of its kind. */
export async function refOf(kind: IdentifierKind, value: string): Promise<string> {
	const made = await unwrap(api.POST('/api/v1/identifiers/refs', { body: { kind, value } }));
	rememberRef(made.kind, made.ref, made.value);
	return made.ref;
}
