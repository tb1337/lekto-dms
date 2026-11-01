import { describe, expect, it } from 'vitest';
import { MAX_SELECTED, selectionOf } from './selection.ts';

const WHOLE = '01a19889-c51a-7602-b24a-54229b653410';

describe('a selection by link', () => {
	it('takes short and whole ids, comma-separated or repeated, each once', () => {
		const params = new URLSearchParams(`ids=9B653410,${WHOLE}&ids=9b653410&ids=ab12cd34`);
		expect(selectionOf(params)).toEqual(['9b653410', WHOLE, 'ab12cd34']);
	});

	it('leaves out what is no id, and what goes beyond the limit', () => {
		expect(selectionOf(new URLSearchParams('ids=1234,<script>,9b65341x'))).toEqual([]);
		const many = Array.from({ length: MAX_SELECTED + 5 }, (_, n) =>
			n.toString(16).padStart(8, '0')
		);
		expect(selectionOf(new URLSearchParams(`ids=${many.join(',')}`))).toHaveLength(MAX_SELECTED);
		expect(selectionOf(new URLSearchParams(''))).toEqual([]);
	});
});
