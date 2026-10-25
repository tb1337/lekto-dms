import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, type Problem } from '#lib/api/problem.ts';
import { m } from '#lib/paraglide/messages.js';
import FormDialog from './FormDialog.svelte';

// A field that is told the error, as the dialogs' inputs are for `aria-invalid`.
const children = createRawSnippet((error: () => string | null) => ({
	render: () => `<input aria-label="Name" />`,
	setup(node) {
		$effect(() => node.setAttribute('aria-invalid', error() ? 'true' : 'false'));
	}
}));

const TAKEN: Problem = {
	type: 'about:blank',
	title: 'Conflict',
	status: 409,
	detail: 'taken',
	existing_document_id: null,
	space_id: null,
	open_fields: null,
	blocking_spaces: null,
	second_factor_required: null,
	reason: null,
	errors: null
};
const taken = () => Promise.reject(new ApiError(409, TAKEN, null));

function dialog(action: () => Promise<void>) {
	const props = $state({ open: true, title: 'Space', submitLabel: 'Save', action, children });
	render(FormDialog, props);
	return props;
}

describe('FormDialog', () => {
	it('runs the action once, held while it runs, and closes when it succeeds', async () => {
		const user = userEvent.setup();
		let finish!: () => void;
		const action = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
		const props = dialog(action);
		const save = await screen.findByRole('button', { name: 'Save' });
		await user.click(save);
		await user.click(save);
		expect(action).toHaveBeenCalledOnce();
		expect((save as HTMLButtonElement).disabled).toBe(true);
		finish();
		await waitFor(() => expect(props.open).toBe(false));
	});

	it('stays open with the error when the action fails, told to the fields too', async () => {
		const user = userEvent.setup();
		const props = dialog(vi.fn(taken));
		await user.click(await screen.findByRole('button', { name: 'Save' }));
		expect((await screen.findByRole('alert')).textContent).toContain('taken');
		expect(screen.getByLabelText('Name').getAttribute('aria-invalid')).toBe('true');
		expect(props.open).toBe(true);
		expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(
			false
		);
		await user.click(screen.getByRole('button', { name: m.cancel() }));
		await waitFor(() => expect(props.open).toBe(false));
	});
});
