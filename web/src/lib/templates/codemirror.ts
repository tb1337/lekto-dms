/**
 * The template editor itself: CodeMirror with the colours of `liquid.ts`, completion of
 * values, fields, filters and tags, undo and the usual keys. Loaded on demand (`import()`), only
 * where a template is edited; tests replace it with a plain text area (`tests/setup.ts`).
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
	id?: string;
	label?: string;
	describedBy?: string;
	invalid?: boolean;
	maxlength?: number;
	autofocus?: boolean;
}

export interface EditorHandle {
	/** Replace the text, unless it is the same. */
	setValue(value: string): void;
	setInvalid(invalid: boolean): void;
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

const theme = EditorView.theme({
	'&': { fontSize: '0.875rem', backgroundColor: 'transparent' },
	'&.cm-focused': { outline: 'none' },
	'.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '1.5' },
	'.cm-content': { padding: '0.5rem 0', caretColor: 'var(--foreground)' },
	'.cm-line': { padding: '0 0.75rem' },
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
	'.cm-completionDetail': { fontFamily: 'var(--font-sans)', color: 'var(--muted-foreground)' }
});

/** The completions at the cursor: values and fields in an expression, a field's key after
 * `field.`, filters after `|`, tags after `{%`. A value picked in a `{{` without its `}}` gets
 * it. */
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
			case 'value':
				options = [
					...names.map((name) => ({
						label: name.name,
						apply: name.name + close,
						detail: name.label,
						type: 'variable'
					})),
					...fields.map((field) => ({
						label: `field.${field.key}`,
						apply: `field.${field.key}${close}`,
						detail: field.name,
						type: 'property'
					}))
				];
				break;
		}
		return { from: spot.from, options, validFor: /^\w*$/ };
	};
}

function attributes(options: EditorOptions, invalid: boolean): Record<string, string> {
	const result: Record<string, string> = {
		'aria-multiline': 'true',
		spellcheck: 'false',
		autocorrect: 'off',
		autocapitalize: 'off'
	};
	if (options.id) result.id = options.id;
	if (options.label) result['aria-label'] = options.label;
	if (options.describedBy) result['aria-describedby'] = options.describedBy;
	if (invalid) result['aria-invalid'] = 'true';
	return result;
}

export function mountTemplateEditor(options: EditorOptions): EditorHandle {
	const content = new Compartment();
	const max = options.maxlength ?? 500;
	const view = new EditorView({
		parent: options.parent,
		state: EditorState.create({
			doc: options.value,
			extensions: [
				history(),
				keymap.of([...completionKeymap, ...defaultKeymap, ...historyKeymap]),
				autocompletion({ override: [completionSource(options.completions)], icons: false }),
				EditorView.lineWrapping,
				EditorState.changeFilter.of((transaction) => transaction.newDoc.length <= max),
				content.of(EditorView.contentAttributes.of(attributes(options, Boolean(options.invalid)))),
				colours,
				theme,
				EditorView.updateListener.of((update) => {
					if (update.docChanged) options.onchange(update.state.doc.toString());
				})
			]
		})
	});
	if (options.autofocus) view.focus();
	return {
		setValue(value) {
			const current = view.state.doc.toString();
			if (value === current) return;
			view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
		},
		setInvalid(invalid) {
			view.dispatch({
				effects: content.reconfigure(EditorView.contentAttributes.of(attributes(options, invalid)))
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
		}
	};
}
