import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Markdown from '#lib/components/document/Markdown.svelte';
import { lex, safeHref } from './markdown.ts';

describe('markdown', () => {
	it('lexes tables as GitHub does', () => {
		expect(lex('| a | b |\n|---|---|\n| 1 | 2 |\n')[0].type).toBe('table');
	});

	it('follows web and mail links only', () => {
		expect(safeHref('https://stadtwerke.example/rechnung')).toBe(
			'https://stadtwerke.example/rechnung'
		);
		expect(safeHref('mailto:service@stadtwerke.example')).toBe('mailto:service@stadtwerke.example');
		expect(safeHref('javascript:alert(1)')).toBeNull();
		expect(safeHref('data:text/html,x')).toBeNull();
		expect(safeHref(undefined)).toBeNull();
	});
});

describe('Markdown', () => {
	it('renders the structure as elements', () => {
		const { container } = render(Markdown, {
			source:
				'# Stadtwerke\n\nBetrag **84,20 €**\n\n| Position | Betrag |\n|---|---|\n| Grundpreis | 12,07 € |\n\n- eins\n- zwei\n'
		});
		expect(container.querySelector('h2')?.textContent).toBe('Stadtwerke');
		expect(container.querySelector('strong')?.textContent).toBe('84,20 €');
		expect(container.querySelectorAll('td')[1].textContent?.trim()).toBe('12,07 €');
		expect(container.querySelectorAll('li')).toHaveLength(2);
	});

	it('never turns text of the document into markup', () => {
		const { container } = render(Markdown, {
			source:
				'Hallo <script>alert(1)</script> <img src=x onerror=alert(1)> [klick](javascript:alert(1))\n\n<!-- image -->\n'
		});
		expect(container.querySelector('script')).toBeNull();
		expect(container.querySelector('img')).toBeNull();
		expect(container.querySelector('a')).toBeNull();
		expect(container.textContent).toContain('<script>');
		expect(container.textContent).toContain('klick');
		expect(container.textContent).not.toContain('<!-- image -->');
	});
});
