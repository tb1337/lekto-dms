import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import JsonTree from './JsonTree.svelte';

const structure = {
	schema_name: 'DoclingDocument',
	pages: { '1': { page_no: 1 } },
	texts: Array.from({ length: 150 }, (_, index) => ({ text: `Zeile ${index}`, label: 'text' })),
	origin: null
};

describe('JsonTree', () => {
	it('opens the top and folds the rest with its size', () => {
		const { container } = render(JsonTree, { value: structure });
		expect(container.textContent).toMatch(/"schema_name":\s"DoclingDocument"/);
		expect(screen.getByText(m.json_items({ count: '150' }))).toBeTruthy();
		expect(screen.getByText(m.json_key())).toBeTruthy();
		// What is folded is not built.
		expect(container.textContent).not.toContain('Zeile 0');
	});

	it('builds a list when opened, a long one in steps', async () => {
		const { container } = render(JsonTree, { value: structure });
		const texts = screen.getByText(m.json_items({ count: '150' })).closest('details')!;
		texts.open = true;
		texts.dispatchEvent(new Event('toggle'));
		await tick();
		const words = () => (container.textContent ?? '').replace(/\s+/g, ' ');
		expect(words()).toContain('0: {');
		expect(texts.querySelectorAll(':scope > details').length).toBe(100);
		await userEvent.click(
			screen.getByRole('button', { name: m.json_more({ count: '50', total: '50' }) })
		);
		expect(texts.querySelectorAll(':scope > details').length).toBe(150);
	});
});
