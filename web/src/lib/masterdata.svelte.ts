/**
 * Contacts, document types, tags, fields and spaces, as the pickers and filters need them.
 * They are few per household; loaded in full, once per page that needs them.
 */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import { editableSpaces, handOverTargets } from '#lib/permissions.ts';
import { scope } from '#lib/scope.svelte.ts';

export type Contact = components['schemas']['ContactOut'];
export type DocumentType = components['schemas']['DocumentTypeOut'];
/** What every kind of master data has. */
export type MasterData = Pick<Contact, 'id' | 'name' | 'created_at' | 'document_count'>;
export type Tag = components['schemas']['TagOut'];
export type TagScope = components['schemas']['TagScope'];
export type FieldDefinition = components['schemas']['FieldOut'];
export type Space = components['schemas']['SpaceOut'];
export type UserName = components['schemas']['UserOut'];

export interface Lookup {
	contacts: Contact[];
	documentTypes: DocumentType[];
	/** Of every scope: document tags, contact groups, type groups. */
	tags: Tag[];
	fields: FieldDefinition[];
	spaces: Space[];
	users: UserName[];
	/** The webhooks the caller sees (their own; an admin's: everybody's), where a page loaded
	 * them (the rule pages: a rule sends through its author's webhooks). */
	webhooks?: WebhookName[];
}

/** A webhook as a rule names it. */
export interface WebhookName {
	id: string;
	name: string;
	owner_id: string;
}

/** The master data; the spaces follow the reach of the lists (`scope`): an admin gets every
 * space only with "Alle Nutzer einbeziehen", otherwise the ones they are a member of, like
 * everyone (Tobi, 22.10.2026). A page that keeps it loads it again when the reach changes. */
export async function loadLookup(): Promise<Lookup> {
	const [contacts, documentTypes, tags, fields, spaces, users] = await Promise.all([
		unwrap(api.GET('/api/v1/contacts')),
		unwrap(api.GET('/api/v1/document-types')),
		unwrap(api.GET('/api/v1/tags')),
		unwrap(api.GET('/api/v1/fields')),
		unwrap(api.GET('/api/v1/spaces', { params: { query: { all_users: scope.query } } })),
		unwrap(api.GET('/api/v1/users'))
	]);
	return { contacts, documentTypes, tags, fields, spaces, users };
}

/** The master data with the webhooks the caller sees, for the rule pages. */
export async function loadRuleLookup(): Promise<Lookup> {
	const [lookup, webhooks] = await Promise.all([loadLookup(), unwrap(api.GET('/api/v1/webhooks'))]);
	return {
		...lookup,
		webhooks: webhooks.map(({ id, name, owner_id }) => ({ id, name, owner_id }))
	};
}

const indexes = new WeakMap<readonly { id: string }[], ReadonlyMap<string, { id: string }>>();

/** The entries of a list of master data by id, built once per list: a grid of fifty cards
 * resolves its contacts, types and spaces from it in O(1) on every render instead of scanning
 * thousands of entries each. A list loaded anew (`loadLookup`) gets an index of its own. */
export function byId<T extends { id: string }>(list: readonly T[]): ReadonlyMap<string, T> {
	let index = indexes.get(list) as ReadonlyMap<string, T> | undefined;
	if (!index) {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		index = new Map(list.map((entry) => [entry.id, entry]));
		indexes.set(list, index);
	}
	return index;
}

/** Name by id for a list of master data. */
export function names(list: readonly { id: string; name: string }[]): Map<string, string> {
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	return new Map(list.map((entry) => [entry.id, entry.name]));
}

/** The fields that apply to a document type: global ones and those listed for it. */
export function fieldsFor(
	fields: readonly FieldDefinition[],
	documentTypeId: string | null
): FieldDefinition[] {
	return fields.filter(
		(field) =>
			field.document_type_ids === null ||
			(documentTypeId !== null && field.document_type_ids.includes(documentTypeId))
	);
}

/** A space's name; a personal space is "Personal" for its user and its user's name for others. */
export function spaceLabel(
	space: Pick<Space, 'name' | 'personal_of'>,
	users: readonly UserName[],
	me: string | undefined
): string {
	if (space.personal_of === null) return space.name;
	if (space.personal_of === me) return m.space_personal();
	return userName(users, space.personal_of);
}

/** A user's name by id; "unknown" for one the list lacks (none, or a user deleted since): an
 * id says nothing to a reader. */
export function userName(users: readonly UserName[], id: string | null | undefined): string {
	const user = id ? byId(users).get(id) : undefined;
	return user ? userLabel(user) : m.user_unknown();
}

/** How a user is shown: their display name, else their username. */
export function userLabel(user: { username: string; display_name?: string | null }): string {
	return user.display_name ?? user.username;
}

/** How a user is offered for a choice (a member, a hand-over, whose number): the display name
 * with the username beside it where they differ ("Anna Busch (anna)"), so that a display name
 * chosen to look like another user's cannot pass for them. */
export function userChoice(user: { username: string; display_name?: string | null }): string {
	const shown = userLabel(user);
	return shown.toLowerCase() === user.username.toLowerCase()
		? shown
		: `${shown} (${user.username})`;
}

/** The user whose personal space `spaceId` is, as far as `users` tell. */
export function holderOf(users: readonly UserName[], spaceId: string): UserName | undefined {
	return users.find((user) => user.personal_space_id === spaceId);
}

/**
 * A space as the caller names it: by its label if they see it; another user's personal space,
 * which they need not see, by that user ("Personal" for their own); a space they cannot tell
 * by `unseen`.
 */
export function spaceNameFor(
	spaceId: string,
	lookup: Pick<Lookup, 'spaces' | 'users'> | null,
	me: string | undefined,
	unseen: string = m.space_unseen()
): string {
	if (!lookup) return unseen;
	const space = byId(lookup.spaces).get(spaceId);
	if (space) return spaceLabel(space, lookup.users, me);
	const holder = holderOf(lookup.users, spaceId);
	if (holder) return holder.id === me ? m.space_personal() : userLabel(holder);
	return unseen;
}

/** The name of a space the caller is no member of (an admin sees every space), for a badge on a
 * document lying there; null for the caller's own spaces. */
export function foreignSpace(
	spaceId: string,
	lookup: Pick<Lookup, 'spaces' | 'users'> | null,
	me: string | undefined
): string | null {
	const space = lookup ? byId(lookup.spaces).get(spaceId) : undefined;
	if (!space || space.members.some((member) => member.user_id === me)) return null;
	return spaceLabel(space, lookup?.users ?? [], me);
}

/** What a listed document's card or row names (`DocumentCard`, `DocumentRow`): its contact and
 * type, by the indexes of the lists (one of many must not scan them on every render), and for
 * an admin the space it stands in when they are no member of it. */
export function documentParts(
	document: { contact_id?: string | null; document_type_id?: string | null; space_id: string },
	lookup: Lookup | null,
	me: string | undefined
): {
	contact: Lookup['contacts'][number] | undefined;
	kind: Lookup['documentTypes'][number] | undefined;
	foreign: string | null;
} {
	return {
		contact:
			lookup && document.contact_id ? byId(lookup.contacts).get(document.contact_id) : undefined,
		kind:
			lookup && document.document_type_id
				? byId(lookup.documentTypes).get(document.document_type_id)
				: undefined,
		foreign: foreignSpace(document.space_id, lookup, me)
	};
}

/** The spaces a document goes to, as options: those the caller edits, then the other users'
 * personal spaces, as a hand-over ("Hand over to Anna"). */
export function spaceOptions(
	spaces: readonly Space[],
	users: readonly UserName[],
	user: { id: string; role?: UserName['role'] } | null
): { value: string; label: string }[] {
	const editable = editableSpaces(spaces, user);
	const offered = editable.map((space) => space.id);
	return [
		...editable.map((space) => ({
			value: space.id,
			label: spaceLabel(space, users, user?.id)
		})),
		// A personal space the caller edits is offered as itself above.
		...handOverTargets(users, user)
			.filter((other) => !offered.includes(other.personal_space_id))
			.map((other) => ({
				value: other.personal_space_id,
				label: m.move_hand_over({ name: userChoice(other) })
			}))
	];
}
