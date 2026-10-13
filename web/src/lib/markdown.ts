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
	return token.text.trim().startsWith('<!--') ? '' : token.text;
}
