import { describe, expect, it } from 'vitest';
import { addChips } from '#lib/chips.ts';

describe('addChips', () => {
	it('adds each line once, trimmed, and leaves out empty lines and known values', () => {
		expect(addChips(['Nord AG'], ' Nord KV \n\n  \nnord ag\nNord KV')).toEqual([
			'Nord AG',
			'Nord KV'
		]);
		expect(addChips([], '')).toEqual([]);
		expect(addChips([], 'Meier, Müller & Partner')).toEqual(['Meier, Müller & Partner']);
	});
});
