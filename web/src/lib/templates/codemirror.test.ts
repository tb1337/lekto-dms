import { CompletionContext } from '@codemirror/autocomplete';
import { EditorState } from '@codemirror/state';
import { describe, expect, it, vi } from 'vitest';

// The real editor here, not the text area the other tests get.
vi.unmock('#lib/templates/codemirror.ts');
const { completionSource, mountTemplateEditor } = await import('./codemirror.ts');

const lists = () => ({
	names: [{ name: 'contact', label: 'Contact' }],
	fields: [{ key: 'la_brutto', name: 'LA_Brutto' }]
});

function complete(text: string) {
	const state = EditorState.create({ doc: text });
	return completionSource(lists)(new CompletionContext(state, text.length, false));
}

describe('completion', () => {
	it('offers values and fields after {{ and closes the braces', () => {
		const result = complete('Lohn {{ ');
		expect(result?.from).toBe(8);
		expect(result?.options.map((option) => [option.label, option.apply])).toEqual([
			['contact', 'contact }}'],
			['field.la_brutto', 'field.la_brutto }}']
		]);
	});

	it('offers field keys after field., filters after | and tags after {%', () => {
		expect(complete('{{ field.la }}'.slice(0, 11))?.options.map((option) => option.label)).toEqual([
			'la_brutto'
		]);
		const filters = complete('{{ contact | ');
		expect(filters?.options.find((option) => option.label === 'date')?.apply).toBe("date: '%Y-%m'");
		expect(complete('{% ')?.options.map((option) => option.label)).toContain('if');
		expect(complete('Lohn ')).toBeNull();
	});
});

describe('editor', () => {
	it('colours the template and edits at the selection', () => {
		const parent = document.createElement('div');
		document.body.append(parent);
		const changes: string[] = [];
		const editor = mountTemplateEditor({
			parent,
			value: '{{ contact }}',
			onchange: (value) => changes.push(value),
			completions: lists,
			label: 'Title'
		});
		expect(parent.querySelector('.tpl-variable')?.textContent).toBe('contact');
		expect(parent.querySelector('[aria-label="Title"]')).not.toBeNull();
		editor.setValue('Lohn ');
		editor.edit((text) => ({ text: `${text}{{ pages }}`, cursor: 16 }));
		expect(changes.at(-1)).toBe('Lohn {{ pages }}');
		editor.setInvalid(true);
		expect(parent.querySelector('[aria-invalid="true"]')).not.toBeNull();
		editor.destroy();
		parent.remove();
	});
});
