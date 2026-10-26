// Every checkbox and radio button is a `ChoiceBox` (alone, or within a `Choice` with its text):
// no raw `<input type="checkbox">` or `<input type="radio">` in the markup.
import { parse } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';

const sources = import.meta.glob<string>('/src/**/*.svelte', {
	query: '?raw',
	import: 'default',
	eager: true
});

// The component itself, and the text input whose type is a prop.
const ALLOWED_FILES = new Set([
	'/src/lib/components/ui/choice/choice-box.svelte',
	'/src/lib/components/ui/input/input.svelte'
]);
const CHOICE_TYPES = new Set(['checkbox', 'radio']);

interface Node {
	type?: string;
	[key: string]: unknown;
}

/** The `type` of each `<input>`: its static value, or `null` when it is an expression. */
function inputTypes(source: string): (string | null)[] {
	const found: (string | null)[] = [];
	const visit = (value: unknown): void => {
		if (Array.isArray(value)) {
			value.forEach(visit);
			return;
		}
		if (!value || typeof value !== 'object') return;
		const node = value as Node;
		if (node.type === 'RegularElement' && node.name === 'input') {
			const attributes = Array.isArray(node.attributes) ? (node.attributes as Node[]) : [];
			const type = attributes.find((a) => a.type === 'Attribute' && a.name === 'type');
			if (type) {
				const parts = Array.isArray(type.value) ? (type.value as Node[]) : [];
				const text = parts.length === 1 && parts[0].type === 'Text' ? parts[0].data : null;
				found.push(typeof text === 'string' ? text : null);
			}
		}
		for (const [key, child] of Object.entries(node)) {
			if (key === 'instance' || key === 'module' || key === 'css') continue;
			visit(child);
		}
	};
	visit(parse(source, { modern: true }).fragment);
	return found;
}

/** Inputs that are, or may be, a checkbox or radio button. */
function findings(source: string): (string | null)[] {
	return inputTypes(source).filter((type) => type === null || CHOICE_TYPES.has(type));
}

describe('choices', () => {
	it('finds the components', () => {
		expect(Object.keys(sources).length).toBeGreaterThan(20);
	});

	it.each(Object.keys(sources).filter((file) => !ALLOWED_FILES.has(file)))(
		'%s has no raw checkbox or radio',
		(file) => {
			expect(findings(sources[file])).toEqual([]);
		}
	);

	it('notices raw checkboxes, radios and dynamic types', () => {
		expect(findings('<input type="checkbox" />')).toEqual(['checkbox']);
		expect(findings('<label><input type="radio" name="a" /></label>')).toEqual(['radio']);
		expect(findings('<input type={kind} />')).toEqual([null]);
		expect(findings('<input type="text" /><input />')).toEqual([]);
	});
});
