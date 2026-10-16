import { afterEach, describe, expect, it } from 'vitest';
import { rememberSort, rememberView, rememberedView, sortOf } from './listing.ts';

afterEach(() => localStorage.clear());

describe('the sort of the document view', () => {
	it('defaults to relevance for a search and to the newest document date for a list', () => {
		expect(sortOf(new URLSearchParams(), true)).toBe('relevance');
		expect(sortOf(new URLSearchParams(), false)).toBe('-document_date');
	});

	it('takes the URL first, then what this browser chose, each for a list or a search', () => {
		rememberSort('title', false);
		rememberSort('-created_at', true);
		expect(sortOf(new URLSearchParams(), false)).toBe('title');
		expect(sortOf(new URLSearchParams(), true)).toBe('-created_at');
		expect(sortOf(new URLSearchParams('sort=document_date'), false)).toBe('document_date');
		// Relevance only where something is searched; nonsense counts as missing.
		expect(sortOf(new URLSearchParams('sort=relevance'), false)).toBe('title');
		expect(sortOf(new URLSearchParams('sort=size'), true)).toBe('-created_at');
	});

	it('remembers grid or list, grid at first', () => {
		expect(rememberedView()).toBe('grid');
		rememberView('list');
		expect(rememberedView()).toBe('list');
	});
});
