import { fireEvent, render, screen } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { SEPARATOR } from '#lib/tags.ts';
import TagsInput from './TagsInput.svelte';

function tag(id: string, path: string[], parent: string | null, scope = 'document'): Tag {
	return {
		id,
		name: path[path.length - 1],
		path,
		parent_id: parent,
		scope: scope as Tag['scope'],
		assignment: 'auto',
		shown: true,
		created_at: '2026-10-16T12:00:00Z'
	};
}

const ALL = [
	tag('t1', ['Insurance'], null),
	tag('t2', ['Insurance', 'Health'], 't1'),
	tag('t3', ['Paid'], null),
	tag('g1', ['Insurer'], null, 'contact')
];

describe('TagsInput', () => {
	it('shows the leaf with its path as tooltip and removes a tag', async () => {
		const props = $state({ tags: ['t2'], all: ALL, id: 'tags' });
		render(TagsInput, props);
		const chip = screen.getByRole('button', { name: `Insurance${SEPARATOR}Health` });
		expect(chip.textContent?.trim()).toBe('Health');
		expect(chip.closest('[title]')?.getAttribute('title')).toBe(`Insurance${SEPARATOR}Health`);
		await fireEvent.click(
			screen.getByRole('button', {
				name: m.filter_tag_remove({ name: `Insurance${SEPARATOR}Health` })
			})
		);
		expect(props.tags).toEqual([]);
	});

	it('finds a tag by the name of its parent, offers no group, and keeps the child', async () => {
		const user = userEvent.setup();
		const props = $state({ tags: ['t1'], all: ALL, id: 'tags' });
		render(TagsInput, props);
		await user.click(screen.getByRole('button', { name: m.field_tag_add() }));
		const search = await screen.findByLabelText(m.assignment_search());
		expect(screen.queryByText('Insurer')).toBeNull();
		await user.type(search, 'insur');
		expect(screen.getByText('Health')).toBeTruthy();
		expect(screen.queryByText('Paid')).toBeNull();
		await user.click(screen.getByText('Health'));
		expect(props.tags).toEqual(['t2']); // the parent gives way to the child
	});
});
