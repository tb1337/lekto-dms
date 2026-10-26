import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import PromptDialog from './PromptDialog.svelte';

type Call = components['schemas']['ModelCallOut'];

const call = (system: string): Call =>
	({
		system,
		user: 'the text',
		answer: '{}',
		model: 'qwen3:8b',
		usage: { prompt_tokens: 12, completion_tokens: 3 }
	}) as unknown as Call;

afterEach(() => {
	// bits-ui frees the page a moment after a dialog closed; the next test must not wait for it.
	window.document.body.style.pointerEvents = '';
});

describe('PromptDialog', () => {
	it('starts another prompt at its first attempt', async () => {
		const user = userEvent.setup();
		const props = { open: true, title: 'Prompt · Judge', meta: 'qwen3:8b' };
		const { rerender } = render(PromptDialog, {
			...props,
			calls: [call('first of judge'), call('second of judge')]
		});
		await user.click(
			await screen.findByRole('button', { name: m.prompt_attempt({ number: 2, total: 2 }) })
		);
		expect(screen.getByText('second of judge')).toBeTruthy();
		// The same dialog shows the next prompt: its first attempt, not the second.
		await rerender({ ...props, calls: [call('first of reader'), call('second of reader')] });
		expect(screen.getByText('first of reader')).toBeTruthy();
		expect(screen.queryByText('second of reader')).toBeNull();
	});

	it('shows what went to a webhook without a system message', async () => {
		render(PromptDialog, {
			open: true,
			title: 'Prompt · Recognise',
			meta: 'agent 1',
			calls: [call('')]
		});
		expect(await screen.findByText('the text')).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.prompt_system() })).toBeNull();
		expect(screen.getByRole('button', { name: m.prompt_answer() })).toBeTruthy();
	});

	it('shows the parts of a call in the order they were sent, with their tokens', async () => {
		const user = userEvent.setup();
		const sent = {
			system: 'S'.repeat(10),
			user: '',
			document: 'D'.repeat(60),
			task: 'T'.repeat(30),
			retry: null,
			answer: '{}',
			model: 'm',
			usage: { prompt_tokens: 100, completion_tokens: 3 }
		} as unknown as Call;
		const again = { ...sent, retry: 'not JSON' } as unknown as Call;
		render(PromptDialog, { open: true, title: 'Prompt', meta: 'm', calls: [sent, again] });

		const names = [m.prompt_system(), m.prompt_document(), m.prompt_task(), m.prompt_answer()];
		for (const name of names) expect(await screen.findByRole('button', { name })).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.prompt_user() })).toBeNull();
		expect(screen.queryByRole('button', { name: m.prompt_retry() })).toBeNull();
		expect(screen.getByText(m.prompt_parts_note())).toBeTruthy();
		await user.click(screen.getByRole('button', { name: m.prompt_document() }));
		expect(screen.getByText(m.prompt_input({ characters: '60', tokens: '60' }))).toBeTruthy();

		await user.click(
			screen.getByRole('button', { name: m.prompt_attempt({ number: 2, total: 2 }) })
		);
		await user.click(await screen.findByRole('button', { name: m.prompt_retry() }));
		expect(screen.getByText('not JSON')).toBeTruthy();
	});
});
