import { describe, expect, it } from 'vitest';
import { chosen, sourceChips, type Candidate, type CandidateSource } from '#lib/candidates.ts';
import { m } from '#lib/paraglide/messages.js';

const source = (fields: Partial<CandidateSource>) =>
	({ names: false, ...fields }) as CandidateSource;

describe('sourceChips', () => {
	it('names what each signal said, solid where it counts', () => {
		expect(sourceChips(source({ signal: 'signal_llm', names: true, quote: 'Stadtwerke' }))).toEqual(
			[{ text: m.candidate_llm(), strong: true, quote: 'Stadtwerke', note: null, documents: [] }]
		);
		expect(sourceChips(source({ signal: 'signal_llm', score: 0.82 }))[0].text).toBe(
			m.candidate_llm_similar({ score: '82%' })
		);
		expect(sourceChips(source({ signal: 'signal_classifier', score: 0.5 }))[0]).toMatchObject({
			text: m.candidate_classifier({ score: '50%' }),
			strong: false
		});
		expect(
			sourceChips(
				source({ signal: 'signal_neighbours', names: true, votes: 2, found: 3, documents: ['d1'] })
			)[0]
		).toMatchObject({ text: m.candidate_neighbours({ votes: 2, found: 3 }), documents: ['d1'] });
	});

	it('tells the measured value and the threshold it names a value from', () => {
		const model = sourceChips(
			source({ signal: 'signal_llm', names: true, score: 1, threshold: 0.9 })
		);
		expect(model[0]).toMatchObject({
			text: m.candidate_llm_match({ score: '100%', threshold: '90%' }),
			note: m.candidate_llm_note()
		});
		expect(
			sourceChips(source({ signal: 'signal_classifier', score: 0.77, threshold: 0.8 }))[0]
		).toMatchObject({
			text: m.candidate_classifier_threshold({ score: '77%', threshold: '80%' }),
			strong: false
		});
		expect(
			sourceChips(
				source({ signal: 'signal_neighbours', votes: 3, found: 5, similarity: 0.8776 })
			)[0].text
		).toBe(m.candidate_neighbours_similar({ votes: 3, found: 5, similarity: '0.88' }));
	});

	it('gives facts in the text a chip each: they are evidence', () => {
		const chips = sourceChips(
			source({ signal: 'signal_facts', identifiers: ['iban', 'other'], named_in_text: true })
		);
		expect(chips.map((chip) => [chip.text, chip.strong])).toEqual([
			[m.candidate_identifier({ kind: m.identifier_kind_iban() }), true],
			[m.candidate_identifier({ kind: 'other' }), true],
			[m.candidate_named(), true]
		]);
	});
});

describe('chosen', () => {
	const candidate = (value: string | null) => ({ value, label: String(value) }) as Candidate;
	const check = (value: unknown) =>
		({ value, candidates: [candidate('a'), candidate('b'), candidate(null)] }) as Parameters<
			typeof chosen
		>[0];

	it('is the candidate of the value, or those of the tags set', () => {
		expect(chosen(check('b')).map((item) => item.value)).toEqual(['b']);
		expect(chosen(check(['a', 'b'])).map((item) => item.value)).toEqual(['a', 'b']);
		expect(chosen(check(null))).toEqual([]);
		expect(chosen({ value: 'a' } as Parameters<typeof chosen>[0])).toEqual([]);
	});
});
