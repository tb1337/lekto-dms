import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { tokenOf, viaToken } from './via-token.ts';

// DESIGN.md, Names of people: the token a person decided through stands after their name, the
// same way everywhere; every file that has it (`via_token` from the API, or a confirmation or an
// actor of the log, which carry it) and names a person names it through `viaToken`.
const sources = import.meta.glob<string>(
	['/src/**/*.svelte', '/src/**/*.ts', '!/src/**/*.test.ts'],
	{
		query: '?raw',
		import: 'default',
		eager: true
	}
);
const OWN = new Set(['/src/lib/via-token.ts']);
/** What hands a reader the token: the API's field, and the log's readers that carry it. */
const CARRIERS = /via_token|\b(?:tokenOf|confirmationOf|actorOf)\(/;
/** What names a person. */
const NAMES = /\b(?:person|userLabel)\(|inbox_by_you/;

describe('via token', () => {
	it('reads the name of the token from an entry', () => {
		expect(tokenOf({ actor: 'u', via_token: { id: 't', name: 'Claude' } })).toBe('Claude');
		expect(tokenOf({ actor: 'u' })).toBeNull();
		expect(tokenOf({ via_token: { id: 't', name: '' } })).toBeNull();
		expect(tokenOf(null)).toBeNull();
	});

	it('puts the token after the name', () => {
		expect(viaToken('Tobi', 'Claude')).toBe(m.by_token({ name: 'Tobi', token: 'Claude' }));
		expect(viaToken('Tobi', null)).toBe('Tobi');
		expect(viaToken('Tobi', undefined)).toBe('Tobi');
	});

	it('is named through viaToken wherever it is read', () => {
		const readers = Object.entries(sources).filter(
			([path, source]) =>
				!OWN.has(path) &&
				!path.endsWith('/api/schema.ts') &&
				CARRIERS.test(source) &&
				NAMES.test(source)
		);
		expect(readers.map(([path]) => path)).toEqual(
			expect.arrayContaining([
				'/src/lib/components/InboxRow.svelte',
				'/src/lib/components/document/StepEntries.svelte',
				'/src/lib/run-summary.ts',
				'/src/lib/step-summary.ts'
			])
		);
		for (const [path, source] of readers) {
			expect(source, path).toContain('viaToken(');
		}
	});
});
