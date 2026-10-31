// The rules of web/DESIGN.md that a machine can check, over every component and page: tokens
// only (no arbitrary font sizes, radii, shadows or palette colours), one page title, one table,
// tooltips instead of native titles on buttons, dialog widths by their size, icon buttons
// through `IconButton`, one way to view a document (the Beam). An exception needs its line in DESIGN.md ("Exceptions") and here; the
// lists of exceptions may only shrink.
import { describe, expect, it } from 'vitest';

const sources = import.meta.glob<string>('/src/**/*.svelte', {
	query: '?raw',
	import: 'default',
	eager: true
});

/** Files whose markup may break a rule, by rule, each for the reason DESIGN.md gives. */
const EXCEPTIONS = {
	// The wordmark's size on the sign-in page: the logo scales with its font size.
	fontSize: new Set(['/src/routes/login/+page.svelte']),
	// Paper, logos and the QR code are drawn for white; the overlays of shadcn's dialogs.
	palette: new Set([
		'/src/lib/components/document/CodeThumb.svelte',
		'/src/lib/components/DocumentThumb.svelte',
		'/src/lib/components/PageViewer.svelte',
		'/src/lib/components/TotpCard.svelte',
		'/src/lib/components/ContactAvatar.svelte',
		'/src/lib/components/ui/alert-dialog/alert-dialog-overlay.svelte',
		'/src/lib/components/ui/dialog/dialog-overlay.svelte',
		'/src/lib/components/ui/sheet/sheet-overlay.svelte'
	])
} as const;

/** Where the eye (`scan-eye`) stands, which only ever means "show in the Beam" (DESIGN.md, "Beam"):
 * before a document's title and before "Woher gelernt?". */
const EYE = new Set([
	'/src/lib/components/BeamTitle.svelte',
	'/src/lib/components/IdentifiersEditor.svelte'
]);

/** Where a link to one document stands (DESIGN.md, "Beam"): the cards and rows of the lists and
 * the stream's chips build it for `DocumentLink`; "Dokument öffnen" of the Beam; the mark "Im
 * Eingang" and the paging through the inbox, which are navigation. Elsewhere a document's title
 * opens the Beam (`BeamTitle`). */
const DOCUMENT_LINKS = new Set([
	'/src/lib/components/DocumentCard.svelte',
	'/src/lib/components/DocumentRow.svelte',
	'/src/lib/components/InboxRow.svelte',
	'/src/lib/components/documents/StreamView.svelte',
	'/src/lib/components/Beam.svelte',
	'/src/lib/components/InboxMark.svelte',
	'/src/lib/components/document/DocumentHeader.svelte',
	'/src/routes/(app)/documents/[id]/+page.svelte'
]);
const DOCUMENT_LINK = /documentHref\(|inboxDocument\(|BASE\}\/documents\/(?:\{|\$\{)/;

const PALETTE =
	/\b(?:text|bg|border|ring|fill|stroke|outline|decoration|from|to|via)-(?:white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d{2,3})?\b/;

/** The files that break a rule: each with the first offending line. */
function offenders(test: (source: string, path: string) => string | null): string[] {
	const found: string[] = [];
	for (const [path, source] of Object.entries(sources)) {
		const hit = test(source, path);
		if (hit !== null) found.push(`${path}: ${hit.trim().slice(0, 120)}`);
	}
	return found;
}

/** The first line of `source` that matches `pattern`, or null. */
function line(source: string, pattern: RegExp): string | null {
	return source.split('\n').find((text) => pattern.test(text)) ?? null;
}

/** The opening tags of `name` (`<Button ...>`, across lines). */
function tags(source: string, name: string): string[] {
	const found: string[] = [];
	const pattern = new RegExp(`<${name.replace('.', '\\.')}\\b`, 'g');
	for (const match of source.matchAll(pattern)) {
		let depth = 0;
		let end = match.index + match[0].length;
		for (; end < source.length; end++) {
			const char = source[end];
			if (char === '{') depth++;
			else if (char === '}') depth--;
			else if (char === '>' && depth === 0) break;
		}
		found.push(source.slice(match.index, end + 1));
	}
	return found;
}

describe('the design system (web/DESIGN.md)', () => {
	it('takes font sizes from the type scale only', () => {
		expect(
			offenders((source, path) =>
				EXCEPTIONS.fontSize.has(path) ? null : line(source, /\btext-\[\d[\d.]*(?:px|rem|em)\]/)
			)
		).toEqual([]);
	});

	it('takes radii from the tokens only', () => {
		expect(offenders((source) => line(source, /\brounded-(?:3xl|4xl|\[)/))).toEqual([]);
	});

	it('takes shadows from the tokens only', () => {
		expect(offenders((source) => line(source, /\bshadow-\[/))).toEqual([]);
	});

	it('takes colours from the tokens, not from the palette of Tailwind', () => {
		expect(
			offenders((source, path) => (EXCEPTIONS.palette.has(path) ? null : line(source, PALETTE)))
		).toEqual([]);
	});

	it('has one page title: <h1> only in PageTitle', () => {
		expect(
			offenders((source, path) =>
				path.endsWith('/page/PageTitle.svelte') ? null : line(source, /(?<!`)<h1[\s>]/)
			)
		).toEqual([]);
	});

	it('draws every table with ui/table', () => {
		expect(
			offenders((source, path) =>
				path.includes('/components/ui/table/') ? null : line(source, /<table[\s>]/)
			)
		).toEqual([]);
	});

	it('names buttons by tooltips, not by native titles', () => {
		expect(
			offenders((source) => {
				const tagged = ['Button', 'IconButton', 'DropdownMenu.Trigger'].flatMap((name) =>
					tags(source, name)
				);
				return tagged.find((tag) => /\stitle=/.test(tag)) ?? null;
			})
		).toEqual([]);
	});

	it('sizes dialogs by their size, not by a width of their own', () => {
		expect(
			offenders((source) => {
				const tagged = ['Dialog.Content', 'AlertDialog.Content'].flatMap((name) =>
					tags(source, name)
				);
				return tagged.find((tag) => /\bmax-w-(?!none\b)/.test(tag)) ?? null;
			})
		).toEqual([]);
	});

	it('shows the eye only where a click shows a document in the Beam', () => {
		expect(
			offenders((source, path) => (EYE.has(path) ? null : line(source, /icons\/scan-eye['"]/)))
		).toEqual([]);
	});

	it('opens a document directly only from a card of a list or from the Beam', () => {
		expect(
			offenders((source, path) => (DOCUMENT_LINKS.has(path) ? null : line(source, DOCUMENT_LINK)))
		).toEqual([]);
	});

	it('draws icon buttons with IconButton (a label, a tooltip, no round shape)', () => {
		expect(
			offenders((source, path) => {
				if (path.includes('/components/ui/') || path.endsWith('/IconButton.svelte')) return null;
				return tags(source, 'Button').find((tag) => /size="icon/.test(tag)) ?? null;
			})
		).toEqual([]);
	});
});
