import { CompletionContext } from '@codemirror/autocomplete';
import { EditorState } from '@codemirror/state';
import { describe, expect, it, vi } from 'vitest';

// The real editor here, not the text area the other tests get.
vi.unmock('#lib/templates/codemirror.ts');
const { completionSource, mountTemplateEditor } = await import('./codemirror.ts');

const lists = () => ({
	names: [
		{ name: 'title', label: 'Title' },
		{ name: 'contact', label: 'Contact' },
		{ name: 'steps.flow', label: 'Answer of flow' }
	],
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
			['title', 'title }}'],
			['contact', 'contact }}'],
			['steps.flow', 'steps.flow }}'],
			['field.la_brutto', 'field.la_brutto }}']
		]);
		// Listed as given, not by the alphabet.
		const boosts = result?.options.map((option) => option.boost ?? 0) ?? [];
		expect([...boosts].sort((a, b) => b - a)).toEqual(boosts);
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

	it('offers the steps before that ask after steps.', () => {
		expect(complete('{{ steps.')?.options.map((option) => [option.label, option.apply])).toEqual([
			['flow', 'flow }}']
		]);
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
			id: 'title',
			label: 'Title'
		});
		// In a shadow root, where CodeMirror's styles are a constructed sheet, not a <style>.
		const root = parent.querySelector('#title')?.shadowRoot;
		expect(root?.querySelector('.tpl-variable')?.textContent).toBe('contact');
		expect(root?.querySelector('[aria-label="Title"]')).not.toBeNull();
		expect(document.head.querySelector('style')).toBeNull();
		editor.setValue('Lohn ');
		editor.edit((text) => ({ text: `${text}{{ pages }}`, cursor: 16 }));
		expect(changes.at(-1)).toBe('Lohn {{ pages }}');
		editor.setInvalid(true, 'unknown value field.x');
		const field = root?.querySelector('[aria-invalid="true"]');
		expect(field?.getAttribute('aria-description')).toBe('unknown value field.x');
		// Focus inside the editor is not taken for focus that left a dialog's trap.
		const seen: EventTarget[] = [];
		const trap = (event: Event) => seen.push(event.composedPath()[0]);
		document.addEventListener('focusin', trap, { capture: true });
		editor.focus();
		document.removeEventListener('focusin', trap, { capture: true });
		expect(root?.activeElement?.classList.contains('cm-content')).toBe(true);
		expect(seen).toEqual([]);
		editor.destroy();
		expect(parent.childElementCount).toBe(0);
		parent.remove();
	});
});
