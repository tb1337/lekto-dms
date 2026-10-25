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
});
