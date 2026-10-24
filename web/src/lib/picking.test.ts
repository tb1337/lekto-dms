import { describe, expect, it } from 'vitest';
import { flipped, matchesWords, searchWords, toggled } from './picking.ts';

describe('toggled', () => {
	it('adds a value once and removes every copy of it', () => {
		expect(toggled(['a'], 'b', true)).toEqual(['a', 'b']);
		expect(toggled(['a', 'b', 'b'], 'b', false)).toEqual(['a']);
	});

	it('leaves the given list as it was', () => {
		const selected = ['a'];
		toggled(selected, 'b', true);
		expect(selected).toEqual(['a']);
	});
});

describe('flipped', () => {
	it('takes a value out when it is in, else adds it', () => {
		expect(flipped(['a', 'b'], 'a')).toEqual(['b']);
		expect(flipped(['b'], 'a')).toEqual(['b', 'a']);
	});
});

describe('searchWords and matchesWords', () => {
	it('match regardless of case and surrounding space', () => {
		const words = searchWords('  Nord ');
		expect(matchesWords('Nord Versicherung', words)).toBe(true);
		expect(matchesWords('nordsee', words)).toBe(true);
		expect(matchesWords('Süd', words)).toBe(false);
	});

	it('match everything without words', () => {
		expect(searchWords('   ')).toBe('');
		expect(matchesWords('anything', '')).toBe(true);
	});
});
