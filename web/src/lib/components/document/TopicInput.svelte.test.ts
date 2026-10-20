import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
import type { Tag } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import TopicInput from './TopicInput.svelte';

const topic = (id: string, name: string) =>
	({
		id,
		name,
		path: [name],
		parent_id: null,
		scope: 'topic',
		assignment: 'auto',
		shown: true,
		icon: null,
		color: null,
		created_at: '2026-10-17T12:00:00Z'
	}) as Tag;

const WORK = topic('p1', 'Arbeit');

afterEach(() => masterDataDialogs.finishAll());

describe('TopicInput', () => {
	it('offers no topic to create where it is not to (others than admins)', async () => {
		const user = userEvent.setup();
		render(TopicInput, { id: 'topic', topics: [WORK], all: [WORK], placeholder: '—' });
		await user.click(screen.getByRole('combobox'));
		await user.type(await screen.findByLabelText(m.assignment_search()), 'Zahnzusatz');
		expect(screen.queryByText(m.create_named({ name: 'Zahnzusatz' }))).toBeNull();
	});

	it('opens one topic dialog for a double click and chooses the topic it makes', async () => {
		const user = userEvent.setup();
		const props = $state({
			value: '',
			id: 'topic',
			topics: [WORK],
			all: [WORK],
			placeholder: '—',
			creating: true
		});
		render(TopicInput, props);
		await user.click(screen.getByRole('combobox'));
		await user.type(await screen.findByLabelText(m.picker_search_create()), 'Zahnzusatz');
		const offer = screen.getByText(m.create_named({ name: 'Zahnzusatz' }));
		await fireEvent.click(offer);
		await fireEvent.click(offer);
		expect(masterDataDialogs.nested).toMatchObject([{ kind: 'topics', name: 'Zahnzusatz' }]);
		masterDataDialogs.finish(topic('p9', 'Zahnzusatz'));
		await waitFor(() => expect(props.value).toBe('p9'));
	});
});
