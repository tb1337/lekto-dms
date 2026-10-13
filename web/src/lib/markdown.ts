/**
 * Markdown of the parsed text as tokens (`marked`'s lexer, GitHub tables). The tokens are
 * rendered by `Markdown.svelte` into elements, never as HTML: the text comes from a document,
 * a tag in it must not become markup.
 */
import { Lexer, type Token, type Tokens } from 'marked';

export type { Token, Tokens };

export function lex(markdown: string): Token[] {
	return new Lexer({ gfm: true }).lex(markdown);
}

/** A link target that is safe to follow from a document: web and mail addresses only. */
export function safeHref(href: string | null | undefined): string | null {
	const target = (href ?? '').trim();
	return /^(https?:|mailto:)/i.test(target) ? target : null;
}

/** HTML in the Markdown is shown as text, comments (Docling's image placeholders) not at all. */
export function htmlText(token: Tokens.HTML | Tokens.Tag): string {
	return token.text.trim().startsWith('<!--') ? '' : decodeEntities(token.text);
}

const NAMED: Record<string, string> = {
	amp: '&',
	lt: '<',
	gt: '>',
	quot: '"',
	apos: "'",
	nbsp: '\u00a0'
};

/**
 * Text with its HTML entities as characters. The parser writes `&amp;`, `&lt;`, `&gt;` and, in
 * table cells, `&#124;`; the lexer turns only the numbered ones back. The text is shown as
 * text, so nothing of it becomes markup.
 */
export function decodeEntities(text: string): string {
	return text.replace(/&(#x[0-9a-f]{1,6}|#[0-9]{1,7}|[a-z]+);/gi, (entity, name: string) => {
		if (name[0] === '#') {
			const code =
				name[1] === 'x' || name[1] === 'X' ? parseInt(name.slice(2), 16) : Number(name.slice(1));
			return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : entity;
		}
		return NAMED[name.toLowerCase()] ?? entity;
	});
}
