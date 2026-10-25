/**
 * Templates (Liquid) as the editor and the rule view show them: the parts to colour, where a
 * completion fits, and inserting a value or a filter where it belongs. Plain functions over the
 * text, shared by the editor (CodeMirror) and the static view; the server checks the template.
 */

export type TokenKind =
	| 'delimiter'
	| 'tag'
	| 'variable'
	| 'property'
	| 'filter'
	| 'string'
	| 'number'
	| 'operator'
	| 'comment';

export interface Token {
	from: number;
	to: number;
	kind: TokenKind;
}

export interface Segment {
	text: string;
	kind: TokenKind | null;
}

const KEYWORDS: ReadonlySet<string> = new Set([
	'and',
	'or',
	'not',
	'contains',
	'in',
	'with',
	'as',
	'by',
	'reversed',
	'limit',
	'offset'
]);
const CONSTANTS: ReadonlySet<string> = new Set(['true', 'false', 'nil', 'null', 'empty', 'blank']);

/** The tags a template may use (`include` and `render` are not allowed). */
export const TAGS = [
	'if',
	'elsif',
	'else',
	'endif',
	'unless',
	'endunless',
	'case',
	'when',
	'endcase',
	'for',
	'endfor',
	'assign',
	'capture',
	'endcapture',
	'raw',
	'endraw',
	'comment',
	'endcomment'
] as const;

/** Filters to offer, each as it is inserted (with example arguments). */
export const FILTERS: readonly { name: string; insert: string }[] = [
	{ name: 'date', insert: "date: '%Y-%m'" },
	{ name: 'datetime', insert: "datetime: format: 'MMMM yyyy'" },
	{ name: 'default', insert: "default: ''" },
	{ name: 'upcase', insert: 'upcase' },
	{ name: 'downcase', insert: 'downcase' },
	{ name: 'capitalize', insert: 'capitalize' },
	{ name: 'truncate', insert: 'truncate: 30' },
	{ name: 'replace', insert: "replace: 'a', 'b'" },
	{ name: 'remove', insert: "remove: 'a'" },
	{ name: 'append', insert: "append: ' '" },
	{ name: 'prepend', insert: "prepend: ' '" },
	{ name: 'slice', insert: 'slice: 0, 10' },
	{ name: 'strip', insert: 'strip' },
	{ name: 'join', insert: "join: ', '" },
	{ name: 'first', insert: 'first' },
	{ name: 'last', insert: 'last' },
	{ name: 'size', insert: 'size' },
	{ name: 'currency', insert: 'currency' },
	{ name: 'decimal', insert: 'decimal' },
	{ name: 'plus', insert: 'plus: 1' },
	{ name: 'minus', insert: 'minus: 1' },
	{ name: 'round', insert: 'round: 2' }
];

/** The filters offered as chips in the editor. */
export const FILTER_CHIPS = [
	'date',
	'datetime',
	'default',
	'upcase',
	'truncate',
	'replace',
	'join'
];

/** The parts of `template` to colour, in order; plain text between them is left out. */
export function tokenize(template: string): Token[] {
	const tokens: Token[] = [];
	let at = 0;
	while (at < template.length) {
		const open = nextOpen(template, at);
		if (open < 0) break;
		const block = template.startsWith('{%', open);
		const inner = open + (template[open + 2] === '-' ? 3 : 2);
		tokens.push({ from: open, to: inner, kind: 'delimiter' });
		const close = template.indexOf(block ? '%}' : '}}', inner);
		const end =
			close < 0
				? template.length
				: close > inner && template[close - 1] === '-'
					? close - 1
					: close;
		const tag = expression(template, inner, end, block, tokens);
		if (close < 0) break;
		tokens.push({ from: end, to: close + 2, kind: 'delimiter' });
		at = close + 2;
		if (tag === 'raw' || tag === 'comment') {
			const closing = new RegExp(`\\{%-?\\s*end${tag}\\s*-?%\\}`, 'g');
			closing.lastIndex = at;
			const found = closing.exec(template);
			const stop = found ? found.index : template.length;
			if (tag === 'comment' && stop > at) tokens.push({ from: at, to: stop, kind: 'comment' });
			at = stop;
		}
	}
	return tokens;
}

/** `template` cut into coloured parts and the plain text between them. */
export function segments(template: string): Segment[] {
	const parts: Segment[] = [];
	let at = 0;
	for (const token of tokenize(template)) {
		if (token.from > at) parts.push({ text: template.slice(at, token.from), kind: null });
		parts.push({ text: template.slice(token.from, token.to), kind: token.kind });
		at = token.to;
	}
	if (at < template.length) parts.push({ text: template.slice(at), kind: null });
	return parts;
}

function nextOpen(text: string, from: number): number {
	const value = text.indexOf('{{', from);
	const tag = text.indexOf('{%', from);
	if (value < 0) return tag;
	if (tag < 0) return value;
	return Math.min(value, tag);
}

/** The tokens of one `{{ … }}` or `{% … %}`; returns the tag's name (`if`, `raw`). */
function expression(
	text: string,
	from: number,
	to: number,
	block: boolean,
	tokens: Token[]
): string | null {
	let at = from;
	let first = block;
	let filter = false;
	let tag: string | null = null;
	while (at < to) {
		const char = text[at];
		if (/\s/.test(char)) {
			at++;
			continue;
		}
		const rest = text.slice(at, to);
		if (first && char === '#') {
			tokens.push({ from: at, to, kind: 'comment' });
			return '#';
		}
		if (char === '"' || char === "'") {
			const close = text.indexOf(char, at + 1);
			const stop = close < 0 || close >= to ? to : close + 1;
			tokens.push({ from: at, to: stop, kind: 'string' });
			at = stop;
		} else if (/^-?\d/.test(rest)) {
			const number = /^-?\d+(?:\.\d+)?/.exec(rest)![0];
			tokens.push({ from: at, to: at + number.length, kind: 'number' });
			at += number.length;
		} else if (/^[A-Za-z_]/.test(rest)) {
			const word = /^[A-Za-z_][\w-]*\??/.exec(rest)![0];
			const kind: TokenKind = first
				? 'tag'
				: filter
					? 'filter'
					: text[at - 1] === '.'
						? 'property'
						: CONSTANTS.has(word)
							? 'number'
							: KEYWORDS.has(word)
								? 'operator'
								: 'variable';
			if (first) tag = word;
			tokens.push({ from: at, to: at + word.length, kind });
			at += word.length;
		} else {
			const operator = /^(?:==|!=|<>|<=|>=|\.\.)/.exec(rest)?.[0] ?? char;
			tokens.push({ from: at, to: at + operator.length, kind: 'operator' });
			at += operator.length;
			filter = char === '|';
			first = false;
			continue;
		}
		first = false;
		filter = false;
	}
	return tag;
}

/** Where `{{` or `{%` opens the expression the cursor is in; -1 outside of one. */
export function openAt(text: string, cursor: number): number {
	const before = text.slice(0, cursor);
	const open = Math.max(before.lastIndexOf('{{'), before.lastIndexOf('{%'));
	if (open < 0) return -1;
	const close = before.startsWith('{%', open) ? '%}' : '}}';
	return before.indexOf(close, open + 2) < 0 ? open : -1;
}

export type SpotKind = 'value' | 'field' | 'step' | 'filter' | 'tag';

/** What fits at the cursor: a value, a field's key after `field.`, a filter after `|`, or a
 * tag after `{%`; `from` is where the word typed so far begins. */
export interface Spot {
	kind: SpotKind;
	from: number;
	/** Inside `{{ … }}` (else `{% … %}`). */
	value: boolean;
}

export function completionSpot(text: string, cursor: number): Spot | null {
	const open = openAt(text, cursor);
	if (open < 0) return null;
	const value = text.startsWith('{{', open);
	const inner = text.slice(open + 2, cursor);
	const word = /\w*$/.exec(inner)![0];
	const from = cursor - word.length;
	const lead = inner.slice(0, inner.length - word.length);
	if (/\|\s*$/.test(lead)) return { kind: 'filter', from, value };
	if (/(?:^|[^\w.])field\.$/.test(lead)) return { kind: 'field', from, value };
	if (/(?:^|[^\w.])steps\.$/.test(lead)) return { kind: 'step', from, value };
	if (lead.endsWith('.')) return null;
	if (!value && /^-?\s*$/.test(lead)) return { kind: 'tag', from, value };
	const starts =
		/^-?\s*$/.test(lead) ||
		/[:,(=<>![]\s*$/.test(lead) ||
		/(?:^|\s)(?:and|or|not|contains|in|if|elsif|unless|when|case)\s+$/.test(lead);
	return starts ? { kind: 'value', from, value } : null;
}

/** Whether the `{{` open at the cursor has no `}}` after it yet (before the next expression). */
export function unclosed(text: string, cursor: number): boolean {
	const rest = text.slice(cursor);
	const close = rest.indexOf('}}');
	const next = nextOpen(rest, 0);
	return close < 0 || (next >= 0 && next < close);
}

export interface Edit {
	text: string;
	/** Where the cursor goes. */
	cursor: number;
}

function replaced(text: string, from: number, to: number, insert: string): Edit {
	return { text: text.slice(0, from) + insert + text.slice(to), cursor: from + insert.length };
}

/** `{{ path }}` (a list joined) at the selection, a space apart from an expression right
 * before it; inside an expression just the path. */
export function insertValue(
	text: string,
	from: number,
	to: number,
	path: string,
	list = false
): Edit {
	if (openAt(text, from) >= 0) {
		const pad = /[\s([{]$/.test(text.slice(0, from)) ? '' : ' ';
		return replaced(text, from, to, pad + path);
	}
	const pad = /[}%]\}$/.test(text.slice(0, from)) ? ' ' : '';
	return replaced(text, from, to, pad + (list ? `{{ ${path} | join: ', ' }}` : `{{ ${path} }}`));
}

/** A filter where it belongs: at the cursor inside an expression, or into the expression that
 * ends right before the cursor (`{{ contact }}|` becomes `{{ contact | upcase }}|`). */
export function insertFilter(text: string, from: number, to: number, filter: string): Edit {
	const before = text.slice(0, from);
	if (openAt(text, from) < 0) {
		const closed = /-?\}\}\s*$/.exec(before);
		if (closed) {
			const at = closed.index;
			const pad = /\s$/.test(text.slice(0, at)) ? '' : ' ';
			const insert = `${pad}| ${filter} `;
			const edit = replaced(text, at, at, insert);
			return { text: edit.text, cursor: from + insert.length };
		}
	}
	const pad = /\s$/.test(before) ? '' : ' ';
	return replaced(text, from, to, `${pad}| ${filter}`);
}
