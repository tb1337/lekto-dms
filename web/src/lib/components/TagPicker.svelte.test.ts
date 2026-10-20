import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import type { Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import { SEPARATOR } from '#lib/tags.ts';
import TagPicker from './TagPicker.svelte';

function tag(id: string, path: string[], parent: string | null, scope = 'contact'): Tag {
	return {
		id,
		name: path[path.length - 1],
		path,
		parent_id: parent,
		scope: scope as Tag['scope'],
		assignment: 'manual',
		shown: false,
		icon: null,
		color: null,
		created_at: '2026-10-17T12:00:00Z'
	};
}

const TAGS = [
	tag('g1', ['Insurer'], null),
	tag('g2', ['Insurer', 'Health insurer'], 'g1'),
	tag('g3', ['Bank'], null),
	tag('p1', ['Work'], null, 'topic')
];

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	phone.override(null);
	session.clear();
	masterDataDialogs.finishAll();
	vi.unstubAllGlobals();
	document.body.style.pointerEvents = '';
});

function signIn(role: 'admin' | 'user') {
	session.start({
		user: { id: 'u1', username: 'tobi', role },
		method: 'password',
		expires_at: '2026-10-17T23:00:00Z',
		csrf_token: 'token'
	});
}

function picker(selected: string[] = ['g1']) {
	const made: Tag[] = [];
	const props = $state({
		made,
		oncreated: (created: Tag) => made.push(created),
		id: 'groups',
		label: m.master_groups(),
		title: m.master_contact_groups(),
		scope: 'contact' as const,
		tags: TAGS,
		selected,
		onchange: (next: string[]) => {
			props.selected = next;
		}
	});
	render(TagPicker, props);
	return props;
}

// On a phone the choice is a sheet from the bottom (a dialog); wider, a popover at the button.
describe('TagPicker on a phone', () => {
	beforeEach(() => phone.override(true));

	it('shows the chosen tags as chips to remove', async () => {
		const props = picker(['g1', 'gone']);
		const chips = screen.getByRole('group', { name: m.master_groups() });
		expect(within(chips).getByText('Insurer')).toBeTruthy();
		expect(within(chips).getByText(m.rule_unknown())).toBeTruthy();
		await userEvent.click(
			within(chips).getByRole('button', { name: m.rule_remove_value({ name: 'Insurer' }) })
		);
		expect(props.selected).toEqual(['gone']);
	});

	it('picks in a dialog with the tags of its scope as a tree', async () => {
		const user = userEvent.setup();
		const props = picker();
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const dialog = await screen.findByRole('dialog', { name: m.master_contact_groups() });
		const boxes = within(dialog).getAllByRole('checkbox') as HTMLInputElement[];
		expect(boxes.map((box) => box.getAttribute('aria-label'))).toEqual([
			'Insurer',
			`Insurer${SEPARATOR}Health insurer`,
			'Bank'
		]);
		expect(boxes.map((box) => box.checked)).toEqual([true, false, false]);
		const depth = (box: HTMLElement) => box.closest('label')!.getAttribute('style');
		expect([depth(boxes[0]), depth(boxes[1])]).toEqual(['--depth: 0;', '--depth: 1;']);
		await user.click(boxes[2]);
		expect(props.selected).toEqual(['g1', 'g3']);
		await user.click(within(dialog).getByRole('button', { name: m.picker_done() }));
		expect(screen.queryByRole('dialog')).toBeNull();
	});

	it('opens with an empty search after "Fertig", and tells whether it is open', async () => {
		const user = userEvent.setup();
		picker([]);
		const add = screen.getByRole('button', { name: m.picker_add_group_label() });
		expect(add.getAttribute('aria-expanded')).toBe('false');
		await user.click(add);
		expect(add.getAttribute('aria-expanded')).toBe('true');
		const dialog = await screen.findByRole('dialog');
		await user.type(within(dialog).getByRole('searchbox'), 'Bank');
		await user.click(within(dialog).getByRole('button', { name: m.picker_done() }));
		await waitFor(() => {
			expect(screen.queryByRole('dialog')).toBeNull();
			expect(document.body.style.pointerEvents).not.toBe('none');
		});
		await user.click(add);
		const again = await screen.findByRole('dialog');
		expect((within(again).getByRole('searchbox') as HTMLInputElement).value).toBe('');
		expect(within(again).getAllByRole('checkbox')).toHaveLength(3);
	});

	it('searches the paths and shows all of them when nothing matches', async () => {
		const user = userEvent.setup();
		picker([]);
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const dialog = await screen.findByRole('dialog');
		const search = within(dialog).getByRole('searchbox');
		await user.type(search, 'insurer health');
		expect(within(dialog).getAllByRole('checkbox')).toHaveLength(1);
		expect(within(dialog).getByText(`Insurer${SEPARATOR}Health insurer`)).toBeTruthy();
		await user.clear(search);
		await user.type(search, 'Makler');
		expect(within(dialog).getByText(m.picker_no_match())).toBeTruthy();
		expect(within(dialog).getAllByRole('checkbox')).toHaveLength(3);
	});

	it('lets an admin create a group named as searched in the tag dialog, chosen after', async () => {
		signIn('admin');
		const user = userEvent.setup();
		const props = picker();
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const dialog = await screen.findByRole('dialog');
		const search = within(dialog).getByRole('searchbox');
		// A name that exists (in another case) is chosen, not created.
		await user.type(search, 'bank');
		expect(within(dialog).queryByText(m.create_named({ name: 'bank' }))).toBeNull();
		await user.clear(search);
		await user.type(search, 'Versicherungsmakler ');
		await user.click(within(dialog).getByText(m.create_named({ name: 'Versicherungsmakler' })));
		// The picker gives way to the tag dialog, the name filled in.
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
		expect(masterDataDialogs.nested).toMatchObject([
			{ kind: 'contact-groups', name: 'Versicherungsmakler' }
		]);
		masterDataDialogs.finish(tag('g9', ['Versicherungsmakler'], null));
		await waitFor(() => expect(props.selected).toEqual(['g1', 'g9']));
		expect(props.made.map((made) => made.id)).toEqual(['g9']);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('chooses nothing when the tag dialog closes without', async () => {
		signIn('admin');
		const user = userEvent.setup();
		const props = picker([]);
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		await user.type(within(await screen.findByRole('dialog')).getByRole('searchbox'), 'Makler');
		await user.click(screen.getByText(m.create_named({ name: 'Makler' })));
		masterDataDialogs.finish(null);
		await waitFor(() => expect(masterDataDialogs.nested).toEqual([]));
		expect(props.selected).toEqual([]);
		expect(props.made).toEqual([]);
	});

	it('offers no creating to others than admins', async () => {
		signIn('user');
		const user = userEvent.setup();
		picker([]);
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		await user.type(within(await screen.findByRole('dialog')).getByRole('searchbox'), 'Makler');
		expect(screen.getByText(m.picker_no_match())).toBeTruthy();
		expect(screen.queryByText(m.create_named({ name: 'Makler' }))).toBeNull();
	});
});

describe('TagPicker wider than a phone', () => {
	// The popover is placed by measuring, which jsdom does not: it counts as hidden, and
	// hidden things have no computed name; its title names it.
	const hidden = { hidden: true };
	async function popoverNamed(name: string): Promise<HTMLElement> {
		const popover = await screen.findByRole('dialog', hidden);
		const title = document.getElementById(popover.getAttribute('aria-labelledby') ?? '');
		expect(title?.textContent?.trim()).toBe(name);
		return popover;
	}

	it('picks in a popover at the button, named by the kind', async () => {
		const user = userEvent.setup();
		const props = picker();
		await user.click(screen.getByRole('button', { name: m.picker_add_group_label() }));
		const popover = await popoverNamed(m.master_contact_groups());
		const boxes = within(popover).getAllByRole('checkbox', hidden) as HTMLInputElement[];
		expect(boxes.map((box) => box.getAttribute('aria-label'))).toEqual([
			'Insurer',
			`Insurer${SEPARATOR}Health insurer`,
			'Bank'
		]);
		await user.click(boxes[2]);
		expect(props.selected).toEqual(['g1', 'g3']);
		await user.click(within(popover).getByText(m.picker_done()));
		await waitFor(() => expect(screen.queryByRole('dialog', hidden)).toBeNull());
	});

	it('offers a document only what may be chosen, as the form says', async () => {
		const user = userEvent.setup();
		const documentTags = [
			tag('t1', ['Insurance'], null, 'document'),
			tag('t2', ['Insurance', 'Health'], 't1', 'document'),
			tag('t3', ['Paid'], null, 'document'),
			...TAGS
		];
		render(TagPicker, {
			id: 'tags',
			label: m.field_tags(),
			title: m.field_tags(),
			scope: 'document',
			tags: documentTags,
			selected: ['t2'],
			onchange: () => {},
			// As the document form does: no tag above one set.
			offered: (candidate: Tag) => candidate.id !== 't1'
		});
		await user.click(screen.getByRole('button', { name: m.field_tag_add() }));
		const popover = await popoverNamed(m.field_tags());
		const boxes = within(popover).getAllByRole('checkbox', hidden);
		// No groups, not the tag above the one set; the one set stays to take off.
		expect(boxes.map((box) => box.getAttribute('aria-label'))).toEqual([
			`Insurance${SEPARATOR}Health`,
			'Paid'
		]);
	});

	it('shows only the chips where nothing may change', () => {
		render(TagPicker, {
			id: 'tags',
			label: m.field_tags(),
			title: m.field_tags(),
			scope: 'document',
			tags: [tag('t3', ['Paid'], null, 'document')],
			selected: ['t3'],
			onchange: () => {},
			disabled: true
		});
		expect(screen.getByText('Paid')).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.field_tag_add() })).toBeNull();
		expect(
			screen.queryByRole('button', { name: m.rule_remove_value({ name: 'Paid' }) })
		).toBeNull();
	});
});
