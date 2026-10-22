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

/** A user's name by id; the id while unknown. */
export function userName(users: readonly UserName[], id: string): string {
	return users.find((user) => user.id === id)?.username ?? id;
}

/** The name of a space the caller is no member of (an admin sees every space), for a badge on a
 * document lying there; null for the caller's own spaces. */
export function foreignSpace(
	spaceId: string,
	lookup: Pick<Lookup, 'spaces' | 'users'> | null,
	me: string | undefined
): string | null {
	const space = lookup?.spaces.find((entry) => entry.id === spaceId);
	if (!space || space.members.some((member) => member.user_id === me)) return null;
	return spaceLabel(space, lookup?.users ?? [], me);
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
				label: m.move_hand_over({ name: userName(users, other.id) })
			}))
	];
}
