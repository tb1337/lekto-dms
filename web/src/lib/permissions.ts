/**
 * What the UI offers. The API checks every call; these rules only keep the UI from showing
 * actions it would reject, and from hiding ones it allows. They follow the endpoint descriptions
 * in `openapi.json`: rights hang on the space a document lies in, as the caller's role there
 * (`read`, `edit`); admins have every right and see everything (Tobi, 08.10.2026), so their role
 * is `edit` in every space.
 */
import type { components } from '#lib/api/schema.ts';

type Document = Pick<components['schemas']['DocumentDetails'], 'access'>;
type Actor = {
	id: string;
	role?: components['schemas']['Role'] | null;
	active?: boolean | null;
} | null;
type Owned = { owner_id: string | null };
type SpaceLike = Pick<components['schemas']['SpaceOut'], 'id' | 'role' | 'personal_of'>;
type UserLike = Pick<components['schemas']['UserOut'], 'id' | 'personal_space_id' | 'active'>;
type RuleLike = Pick<components['schemas']['RuleOut'], 'scope' | 'space_id'> & {
	managed_by_document_type_id?: string | null;
};

const isAdmin = (user: Actor): boolean => user?.role === 'admin';
const owns = (item: Owned, user: Actor): boolean => user !== null && item.owner_id === user.id;
const edits = (spaces: readonly SpaceLike[], id: string | null): boolean =>
	spaces.some((space) => space.id === id && space.role === 'edit');

/** Change the metadata, review, retry, reprocess, delete, read the processing log and move:
 * the editors of the document's space and admins (their access is `edit`). */
export function canEdit(document: Document, user: Actor): boolean {
	return user !== null && document.access === 'edit';
}

/** Spaces the caller files into and moves into: the ones they edit (every one for admins), also
 * another user's personal space they edit, which stays theirs to move into when its user is
 * deactivated. Other personal spaces take documents as a hand-over (`handOverTargets`). */
export function editableSpaces<T extends SpaceLike>(spaces: readonly T[], user: Actor): T[] {
	return spaces.filter((space) => user !== null && space.role === 'edit');
}

/** The other users a document is handed over to: into their personal space
 * (`personal_space_id` of `GET /users`), without being a member there. Deactivated users take
 * nothing. */
export function handOverTargets<T extends UserLike>(
	users: readonly T[],
	user: Actor
): (T & { personal_space_id: string })[] {
	return users.filter(
		(other): other is T & { personal_space_id: string } =>
			other.id !== user?.id && other.active !== false && !!other.personal_space_id
	);
}

/** Rename and delete a space: its editors and admins; never a personal space. */
export function canManageSpace(space: SpaceLike, user: Actor): boolean {
	return user !== null && space.personal_of === null && space.role === 'edit';
}

/** Add, change and remove members: the editors of a space and admins; the members of a personal
 * space only its user and admins. */
export function canChooseMembers(space: SpaceLike, user: Actor): boolean {
	if (user === null) return false;
	if (space.personal_of !== null) return space.personal_of === user.id || isAdmin(user);
	return space.role === 'edit';
}

/** Leave a space: every member, a reader too; not the user of a personal space, and not the last
 * editor of a space. */
export function canLeaveSpace(
	space: SpaceLike & { members: readonly { user_id: string; role: string }[] },
	user: Actor
): boolean {
	if (user === null || space.personal_of === user.id) return false;
	const own = space.members.find((member) => member.user_id === user.id);
	if (!own) return false;
	return own.role !== 'edit' || space.members.filter((member) => member.role === 'edit').length > 1;
}

/** Change, delete, test a webhook and renew its secret: its owner and admins. */
export function canManageWebhook(webhook: Owned, user: Actor): boolean {
	return owns(webhook, user) || isAdmin(user);
}

/** The spaces a rule may belong to: those the caller edits (every one for admins). */
export function ruleSpaces<T extends SpaceLike>(spaces: readonly T[]): T[] {
	return spaces.filter((space) => space.role === 'edit');
}

/** Change, enable, disable and delete a rule: a space rule the editors of its space, a global
 * rule admins (admins any rule); the rule of a document type's title pattern nobody (it follows
 * the type). */
export function canChangeRule(rule: RuleLike, user: Actor, spaces: readonly SpaceLike[]): boolean {
	if (rule.managed_by_document_type_id) return false;
	if (isAdmin(user)) return true;
	return user !== null && rule.scope === 'space' && edits(spaces, rule.space_id);
}

/** Apply a rule to existing documents: a space rule the editors of its space and admins; a
 * global rule anyone (on the documents they edit). */
export function canApplyRule(rule: RuleLike, user: Actor, spaces: readonly SpaceLike[]): boolean {
	if (user === null) return false;
	return rule.scope === 'global' || isAdmin(user) || edits(spaces, rule.space_id);
}

/** Lists of every user (documents, inbox, search, rules): admins only. */
export function canListAllUsers(user: Actor): boolean {
	return isAdmin(user);
}
