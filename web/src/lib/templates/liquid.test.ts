import { describe, expect, it } from 'vitest';
import {
	completionSpot,
	insertFilter,
	insertValue,
	segments,
	tokenize,
	unclosed,
	type TokenKind
} from './liquid.ts';

function kinds(template: string): [string, TokenKind][] {
	return tokenize(template).map((token) => [template.slice(token.from, token.to), token.kind]);
}

describe('colours of a template', () => {
	it('tells values, fields, filters and their arguments apart', () => {
		expect(kinds("Lohn {{ field.la_brutto | default: 'x' }} {{ pages | plus: 1 }}")).toEqual([
			['{{', 'delimiter'],
			['field', 'variable'],
			['.', 'operator'],
			['la_brutto', 'property'],
			['|', 'operator'],
			['default', 'filter'],
			[':', 'operator'],
			["'x'", 'string'],
			['}}', 'delimiter'],
			['{{', 'delimiter'],
			['pages', 'variable'],
			['|', 'operator'],
			['plus', 'filter'],
			[':', 'operator'],
			['1', 'number'],
			['}}', 'delimiter']
		]);
	});

	it('knows tags, keywords and whitespace control', () => {
		expect(kinds('{%- if contact and tags contains "Steuer" -%}')).toEqual([
			['{%-', 'delimiter'],
			['if', 'tag'],
			['contact', 'variable'],
			['and', 'operator'],
			['tags', 'variable'],
			['contains', 'operator'],
			['"Steuer"', 'string'],
			['-%}', 'delimiter']
		]);
	});

	it('leaves raw text and comments alone, and single braces are text', () => {
		const template = '{% raw %}{{ x }}{% endraw %} {% comment %}note{% endcomment %} {contact}';
		const parts = segments(template);
		expect(parts.map((part) => part.text).join('')).toBe(template);
		expect(parts.find((part) => part.text === '{{ x }}')?.kind).toBeNull();
		expect(parts.find((part) => part.text === 'note')?.kind).toBe('comment');
		expect(parts.at(-1)).toEqual({ text: ' {contact}', kind: null });
	});

	it('copes with a template typed halfway', () => {
		expect(kinds("{{ contact | date: '%Y")).toEqual([
			['{{', 'delimiter'],
			['contact', 'variable'],
			['|', 'operator'],
			['date', 'filter'],
			[':', 'operator'],
			["'%Y", 'string']
		]);
	});
});

describe('what fits at the cursor', () => {
	const at = (text: string) => completionSpot(text, text.length);

	it('offers values, field keys, filters and tags where they belong', () => {
		expect(at('Lohn {{')).toEqual({ kind: 'value', from: 7, value: true });
		expect(at('Lohn {{ con')).toEqual({ kind: 'value', from: 8, value: true });
		expect(at('{{ field.la')).toEqual({ kind: 'field', from: 9, value: true });
		expect(at('{{ contact | up')).toEqual({ kind: 'filter', from: 13, value: true });
		expect(at('{% ')).toEqual({ kind: 'tag', from: 3, value: false });
		expect(at('{% if do')).toEqual({ kind: 'value', from: 6, value: false });
	});

	it('offers nothing outside an expression or after a value', () => {
		expect(at('Lohn {{ contact }} ')).toBeNull();
		expect(at('{{ contact ')).toBeNull();
		expect(at('{{ field.la_brutto.')).toBeNull();
		expect(at('{contact')).toBeNull();
	});

	it('knows whether a value still needs its closing braces', () => {
		expect(unclosed('{{ con', 6)).toBe(true);
		expect(unclosed('{{ con }}', 6)).toBe(false);
		expect(unclosed('{{ con {{ x }}', 6)).toBe(true);
	});
});

describe('inserting', () => {
	it('writes a value in braces, or just its path inside an expression', () => {
		expect(insertValue('Lohn ', 5, 5, 'contact')).toEqual({
			text: 'Lohn {{ contact }}',
			cursor: 18
		});
		expect(insertValue('', 0, 0, 'tags', true).text).toBe("{{ tags | join: ', ' }}");
		expect(insertValue('{% if  %}', 6, 6, 'field.x')).toEqual({
			text: '{% if field.x %}',
			cursor: 13
		});
	});

	it('puts a filter into the expression it follows', () => {
		expect(insertFilter('{{ contact }}', 13, 13, 'upcase')).toEqual({
			text: '{{ contact | upcase }}',
			cursor: 22
		});
		expect(insertFilter('{{ contact', 10, 10, 'upcase').text).toBe('{{ contact | upcase');
		expect(insertFilter('{{ contact | upcase }}', 22, 22, 'truncate: 30').text).toBe(
			'{{ contact | upcase | truncate: 30 }}'
		);
	});
});
