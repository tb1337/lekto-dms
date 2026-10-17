import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import type { Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
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

afterEach(() => {
	phone.override(null);
	document.body.style.pointerEvents = '';
});

function picker(selected: string[] = ['g1']) {
	const props = $state({
		id: 'groups',
		label: m.master_groups(),
		title: m.master_contact_groups(),
		scope: 'contact' as const,
		tags: TAGS,
		selected,
		onchange: (next: string[]) => (props.selected = next)
	});
	render(TagPicker, props);
	return props;
}

describe('TagPicker', () => {
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
});
