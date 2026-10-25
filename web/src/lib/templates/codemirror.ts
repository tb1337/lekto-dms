/**
 * The template editor itself: CodeMirror with the colours of `liquid.ts`, completion of
 * values, fields, filters and tags, undo and the usual keys. Loaded on demand (`import()`), only
 * where a template is edited; tests replace it with a plain text area (`tests/setup.ts`).
 *
 * It sits in a shadow root: CodeMirror brings its styles as a constructed style sheet there,
 * which the CSP (`style-src 'self'`, no inline `<style>`) lets through; in the document it would
 * write a `<style>` element. The page's style sheet does not reach in, so the theme holds the
 * colours, and ids from outside cannot be referenced (the reason of an error is the field's
 * `aria-description`).
 */
import {
	autocompletion,
	completionKeymap,
	type Completion,
	type CompletionContext,
	type CompletionResult
} from '@codemirror/autocomplete';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { Compartment, EditorState, RangeSetBuilder } from '@codemirror/state';
import {
	Decoration,
	EditorView,
	ViewPlugin,
	keymap,
	tooltips,
	type DecorationSet,
	type ViewUpdate
} from '@codemirror/view';
import {
	FILTERS,
	TAGS,
	completionSpot,
	tokenize,
	unclosed,
	type Edit,
	type TokenKind
} from '#lib/templates/liquid.ts';

export interface Completions {
	/** The values with their labels (`contact`, "Contact"). */
	names: readonly { name: string; label: string }[];
	/** The fields the template may use. */
	fields: readonly { key: string; name: string }[];
}

export interface EditorOptions {
	parent: HTMLElement;
	value: string;
	onchange: (value: string) => void;
	completions: () => Completions;
	/** Of the element that holds the editor. */
	id?: string;
	label?: string;
	invalid?: boolean;
	/** Why the template is invalid, read with the field. */
	reason?: string | null;
	maxlength?: number;
	autofocus?: boolean;
}

export interface EditorHandle {
	/** Replace the text, unless it is the same. */
	setValue(value: string): void;
	setInvalid(invalid: boolean, reason?: string | null): void;
	/** Change the text at the selection, e.g. `insertValue`, and focus the editor. */
	edit(change: (text: string, from: number, to: number) => Edit): void;
	focus(): void;
	destroy(): void;
}

const KINDS: readonly TokenKind[] = [
	'delimiter',
	'tag',
	'variable',
	'property',
	'filter',
	'string',
	'number',
	'operator',
	'comment'
];
const MARKS = Object.fromEntries(
	KINDS.map((kind) => [kind, Decoration.mark({ class: `tpl-${kind}` })])
) as Record<TokenKind, Decoration>;

function decorations(state: EditorState): DecorationSet {
	const builder = new RangeSetBuilder<Decoration>();
	for (const token of tokenize(state.doc.toString())) {
		if (token.to > token.from) builder.add(token.from, token.to, MARKS[token.kind]);
	}
	return builder.finish();
}

const colours = ViewPlugin.fromClass(
	class {
		decorations: DecorationSet;
		constructor(view: EditorView) {
			this.decorations = decorations(view.state);
		}
		update(update: ViewUpdate) {
			if (update.docChanged) this.decorations = decorations(update.state);
		}
	},
	{ decorations: (plugin) => plugin.decorations }
);

const MONO = "'Geist Mono Variable', ui-monospace, monospace";
const SANS = "'Geist Variable', ui-sans-serif, system-ui, sans-serif";

// The colours of `app.css` (`.tpl-*`), which does not reach into the shadow root.
const COLOURS = {
	'.tpl-delimiter, .tpl-operator': { color: 'var(--tpl-delimiter)' },
	'.tpl-tag': { color: 'var(--tpl-tag)', fontWeight: '600' },
	'.tpl-variable': { color: 'var(--tpl-variable)' },
	'.tpl-property': { color: 'var(--tpl-property)' },
	'.tpl-filter': { color: 'var(--tpl-filter)' },
	'.tpl-string': { color: 'var(--tpl-string)' },
	'.tpl-number': { color: 'var(--tpl-number)' },
	'.tpl-comment': { color: 'var(--tpl-delimiter)', fontStyle: 'italic' }
};

const theme = EditorView.theme({
	...COLOURS,
	'&': { fontSize: '0.875rem', backgroundColor: 'transparent', color: 'inherit' },
	'&.cm-focused': { outline: 'none' },
	'.cm-scroller': { fontFamily: MONO, lineHeight: '1.5' },
	// As tall as an input (`h-11`) with one line.
	'.cm-content': { padding: '0.65rem 0', caretColor: 'var(--foreground)' },
	'.cm-line': { padding: '0 1rem' },
	'.cm-tooltip': {
		backgroundColor: 'var(--popover)',
		color: 'var(--popover-foreground)',
		border: '1px solid var(--border)',
		borderRadius: '0.5rem',
		overflow: 'hidden'
	},
	'.cm-tooltip.cm-tooltip-autocomplete > ul': {
		fontFamily: 'var(--font-mono)',
		maxHeight: '14rem'
	},
	'.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': {
		backgroundColor: 'var(--accent)',
		color: 'var(--accent-foreground)'
	},
	'.cm-completionDetail': { fontFamily: SANS, color: 'var(--muted-foreground)' }
});

/** The completions at the cursor: values and fields in an expression (in the order of
 * `names`, then the fields), a field's key after `field.`, filters after `|`, tags after `{%`. A
 * value picked in a `{{` without its `}}` gets it. */
export function completionSource(lists: () => Completions) {
	return (context: CompletionContext): CompletionResult | null => {
		const text = context.state.doc.toString();
		const spot = completionSpot(text, context.pos);
		if (!spot) return null;
		const { names, fields } = lists();
		const close = spot.value && unclosed(text, context.pos) ? ' }}' : '';
		let options: Completion[];
		switch (spot.kind) {
			case 'filter':
				options = FILTERS.map((filter) => ({
					label: filter.name,
					apply: filter.insert,
					detail:
						filter.insert === filter.name ? undefined : filter.insert.slice(filter.name.length),
					type: 'function'
				}));
				break;
			case 'field':
				options = fields.map((field) => ({
					label: field.key,
					apply: field.key + close,
					detail: field.name,
					type: 'property'
				}));
				break;
			case 'tag':
				options = TAGS.map((tag) => ({ label: tag, apply: `${tag} `, type: 'keyword' }));
				break;
			case 'step':
				options = names
					.filter((name) => name.name.startsWith('steps.'))
					.map((name) => {
						const step = name.name.slice('steps.'.length);
						return { label: step, apply: step + close, detail: name.label, type: 'property' };
					});
				break;
			case 'value':
				options = [
					...names.map((name, index) => ({
						label: name.name,
						apply: name.name + close,
						detail: name.label,
						type: 'variable',
						boost: 99 - index
					})),
					...fields.map((field) => ({
						label: `field.${field.key}`,
						apply: `field.${field.key}${close}`,
						detail: field.name,
						type: 'property',
						boost: 50
					}))
				];
				break;
		}
		return { from: spot.from, options, validFor: /^\w*$/ };
	};
}

// The focus trap of bits-ui's dialogs and sheets takes focus in a shadow root for focus that left
// them (`Node.contains` does not look into it) and pulls it back. Focus that goes into an editor
// does not reach it: this listener on the window runs before the trap's on the document.
const roots = new WeakSet<Node>();
window.addEventListener(
	'focusin',
	(event) => {
		const target = event.composedPath()[0];
		if (target instanceof Node && roots.has(target.getRootNode())) event.stopPropagation();
	},
	{ capture: true }
);

/** Where a completion list may go: within the dialog the editor is in (it cuts off what reaches
 * past it), so the list opens above where there is no room below. */
function tooltipSpace(host: HTMLElement) {
	const dialog = host.closest('[role="dialog"]')?.getBoundingClientRect();
	return {
		top: Math.max(0, dialog?.top ?? 0),
		left: Math.max(0, dialog?.left ?? 0),
		bottom: Math.min(window.innerHeight, dialog?.bottom ?? window.innerHeight),
		right: Math.min(window.innerWidth, dialog?.right ?? window.innerWidth)
	};
}

function attributes(
	options: EditorOptions,
	invalid: boolean,
	reason: string | null
): Record<string, string> {
	const result: Record<string, string> = {
		'aria-multiline': 'true',
		spellcheck: 'false',
		autocorrect: 'off',
		autocapitalize: 'off'
	};
	if (options.label) result['aria-label'] = options.label;
	if (invalid) result['aria-invalid'] = 'true';
	if (reason) result['aria-description'] = reason;
	return result;
}

export function mountTemplateEditor(options: EditorOptions): EditorHandle {
	const content = new Compartment();
	const max = options.maxlength ?? 500;
	const host = document.createElement('div');
	if (options.id) host.id = options.id;
	options.parent.append(host);
	const root = host.attachShadow({ mode: 'open' });
	roots.add(root);
	const view = new EditorView({
		parent: root,
		root,
		state: EditorState.create({
			doc: options.value,
			extensions: [
				history(),
				keymap.of([...completionKeymap, ...defaultKeymap, ...historyKeymap]),
				autocompletion({ override: [completionSource(options.completions)], icons: false }),
				tooltips({ tooltipSpace: () => tooltipSpace(host) }),
				EditorView.lineWrapping,
				EditorState.changeFilter.of((transaction) => transaction.newDoc.length <= max),
				content.of(
					EditorView.contentAttributes.of(
						attributes(options, Boolean(options.invalid), options.reason ?? null)
					)
				),
				colours,
				theme,
				EditorView.updateListener.of((update) => {
					if (update.docChanged) options.onchange(update.state.doc.toString());
				})
			]
		})
	});
	if (options.autofocus) {
		view.dispatch({ selection: { anchor: view.state.doc.length } });
		view.focus();
	}
	return {
		setValue(value) {
			const current = view.state.doc.toString();
			if (value === current) return;
			view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
		},
		setInvalid(invalid, reason = null) {
			view.dispatch({
				effects: content.reconfigure(
					EditorView.contentAttributes.of(attributes(options, invalid, reason))
				)
			});
		},
		edit(change) {
			const { from, to } = view.state.selection.main;
			const current = view.state.doc.toString();
			const next = change(current, from, to);
			view.dispatch({
				changes: { from: 0, to: current.length, insert: next.text },
				selection: { anchor: Math.min(next.cursor, next.text.length) }
			});
			view.focus();
		},
		focus() {
			view.focus();
		},
		destroy() {
			view.destroy();
			host.remove();
		}
	};
}
