import { describe, expect, it } from 'vitest';
import {
	canApplyRule,
	canChangeRule,
	canChooseMembers,
	canEdit,
	canListAllUsers,
	canLeaveSpace,
	canDescribeSpace,
	canManageSpace,
	canManageWebhook,
	editableSpaces,
	handOverTargets,
	ruleSpaces
} from './permissions.ts';

const me = { id: 'u1', role: 'user' as const };
const other = { id: 'u2', role: 'user' as const };
const admin = { id: 'u3', role: 'admin' as const };

describe('document rights', () => {
	it('lets an editor (and an admin, whose access is edit) do everything', () => {
		expect(canEdit({ access: 'edit' }, me)).toBe(true);
		expect(canEdit({ access: 'edit' }, admin)).toBe(true);
	});

	it('lets a reader only read', () => {
		expect(canEdit({ access: 'read' }, me)).toBe(false);
	});

	it('offers nothing without a user', () => {
		expect(canEdit({ access: 'edit' }, null)).toBe(false);
	});
});

// As the API lists them for u1: their personal space, a space they edit, one they read, and
// u2's personal space, which u2 shared with them to read.
const spaces = [
	{ id: 'mine', role: 'edit' as const, personal_of: 'u1' },
	{ id: 'house', role: 'edit' as const, personal_of: null },
	{ id: 'tax', role: 'read' as const, personal_of: null },
	{ id: 'anna', role: 'read' as const, personal_of: 'u2' }
];
const ids = (list: readonly { id: string }[]) => list.map((space) => space.id);

describe('spaces', () => {
	it('files into the spaces the caller edits, another personal one too', () => {
		expect(ids(editableSpaces(spaces, me))).toEqual(['mine', 'house']);
		// A personal space the caller edits stays theirs to file into, as an admin's every space.
		const edited = spaces.map((space) => ({ ...space, role: 'edit' as const }));
		expect(ids(editableSpaces(edited, me))).toEqual(['mine', 'house', 'tax', 'anna']);
		expect(ids(editableSpaces(edited, admin))).toEqual(['mine', 'house', 'tax', 'anna']);
		expect(editableSpaces(spaces, null)).toEqual([]);
	});

	it('lets a member leave a space, not the user of a personal one nor its last editor', () => {
		const members = (...list: [string, 'read' | 'edit'][]) =>
			list.map(([user_id, role]) => ({ user_id, role }));
		const house = { ...spaces[1], members: members(['u1', 'edit'], ['u2', 'read']) };
		expect(canLeaveSpace(house, me)).toBe(false); // the last editor
		expect(canLeaveSpace(house, other)).toBe(true); // a reader
		expect(canLeaveSpace({ ...house, members: members(['u1', 'edit'], ['u2', 'edit']) }, me)).toBe(
			true
		);
		const lent = { ...spaces[3], members: members(['u2', 'edit'], ['u1', 'read']) };
		expect(canLeaveSpace(lent, me)).toBe(true);
		expect(canLeaveSpace(lent, other)).toBe(false); // their own personal space
		expect(canLeaveSpace(house, admin)).toBe(false); // no member
	});

	it('hands over to the other active users, into their personal spaces', () => {
		const users = [
			{ id: 'u1', personal_space_id: 'mine' },
			{ id: 'u2', personal_space_id: 'anna' },
			{ id: 'u4', personal_space_id: 'gone', active: false },
			{ id: 'u5', personal_space_id: null }
		];
		expect(ids(handOverTargets(users, me))).toEqual(['u2']);
		expect(ids(handOverTargets(users, other))).toEqual(['u1']);
	});

	it('lets editors rename and delete a shared space, nobody a personal one', () => {
		expect(canManageSpace(spaces[1], me)).toBe(true);
		expect(canManageSpace(spaces[2], me)).toBe(false);
		expect(canManageSpace(spaces[0], me)).toBe(false);
		expect(canManageSpace(spaces[1], null)).toBe(false);
	});

	it('lets editors describe a space, a personal one too', () => {
		expect(canDescribeSpace(spaces[0], me)).toBe(true);
		expect(canDescribeSpace(spaces[1], me)).toBe(true);
		expect(canDescribeSpace(spaces[2], me)).toBe(false);
		expect(canDescribeSpace(spaces[1], null)).toBe(false);
	});

	it('lets editors choose members; of a personal space its user and admins', () => {
		expect(canChooseMembers(spaces[1], me)).toBe(true);
		expect(canChooseMembers(spaces[2], me)).toBe(false);
		expect(canChooseMembers(spaces[0], me)).toBe(true);
		expect(canChooseMembers({ ...spaces[0], role: 'edit' }, other)).toBe(false);
		expect(canChooseMembers({ ...spaces[0], role: 'edit' }, admin)).toBe(true);
		expect(canChooseMembers(spaces[0], null)).toBe(false);
	});
});

describe('webhooks, lists', () => {
	it('lets the owner and admins manage a webhook', () => {
		const webhook = { owner_id: 'u1' };
		expect(canManageWebhook(webhook, me)).toBe(true);
		expect(canManageWebhook(webhook, admin)).toBe(true);
		expect(canManageWebhook(webhook, other)).toBe(false);
		expect(canManageWebhook(webhook, null)).toBe(false);
	});

	it('lets only admins list every user', () => {
		expect(canListAllUsers(admin)).toBe(true);
		expect(canListAllUsers(me)).toBe(false);
		expect(canListAllUsers(null)).toBe(false);
	});
});

describe('rules', () => {
	const house = { scope: 'space' as const, space_id: 'house' };
	const tax = { scope: 'space' as const, space_id: 'tax' };
	const global = { scope: 'global' as const, space_id: null };

	it('lets the editors of its space change a space rule, admins any rule', () => {
		expect(canChangeRule(house, me, spaces)).toBe(true);
		expect(canChangeRule(tax, me, spaces)).toBe(false);
		expect(canChangeRule(global, me, spaces)).toBe(false);
		expect(canChangeRule(global, admin, [])).toBe(true);
		expect(canChangeRule(house, null, spaces)).toBe(false);
		// The rule of a title pattern follows its document type: nobody changes it here.
		const pattern = { ...global, managed_by_document_type_id: 'type' };
		expect(canChangeRule(pattern, admin, [])).toBe(false);
	});

	it('lets anyone apply a global rule, a space rule its editors and admins', () => {
		expect(canApplyRule(global, other, [])).toBe(true);
		expect(canApplyRule(house, me, spaces)).toBe(true);
		expect(canApplyRule(tax, me, spaces)).toBe(false);
		expect(canApplyRule(tax, admin, [])).toBe(true);
		expect(canApplyRule(global, null, [])).toBe(false);
	});

	it('puts a rule into a space the caller edits', () => {
		expect(ids(ruleSpaces(spaces))).toEqual(['mine', 'house']);
	});
});
