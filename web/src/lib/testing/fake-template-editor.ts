/**
 * The template editor for tests: a plain text area in place of CodeMirror, which jsdom cannot
 * lay out. Same options and handle as `#lib/templates/codemirror.ts`; `tests/setup.ts` puts it in.
 */
import type { EditorHandle, EditorOptions } from '#lib/templates/codemirror.ts';

export function mountTemplateEditor(options: EditorOptions): EditorHandle {
	const area = document.createElement('textarea');
	area.value = options.value;
	if (options.id) area.id = options.id;
	if (options.label) area.setAttribute('aria-label', options.label);
	if (options.describedBy) area.setAttribute('aria-describedby', options.describedBy);
	if (options.invalid) area.setAttribute('aria-invalid', 'true');
	area.maxLength = options.maxlength ?? 500;
	area.addEventListener('input', () => options.onchange(area.value));
	options.parent.append(area);
	if (options.autofocus) area.focus();
	return {
		setValue(value) {
			if (area.value !== value) area.value = value;
		},
		setInvalid(invalid) {
			if (invalid) area.setAttribute('aria-invalid', 'true');
			else area.removeAttribute('aria-invalid');
		},
		edit(change) {
			const next = change(area.value, area.selectionStart, area.selectionEnd);
			area.value = next.text;
			area.setSelectionRange(next.cursor, next.cursor);
			options.onchange(next.text);
			area.focus();
		},
		focus() {
			area.focus();
		},
		destroy() {
			area.remove();
		}
	};
}
