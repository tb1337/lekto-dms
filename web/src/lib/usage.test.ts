import { describe, expect, it } from 'vitest';
import { speed, splitInput, usageOf } from './usage.ts';

describe('usageOf', () => {
	it('sums the attempts and reads the durations of Ollama', () => {
		const usage = usageOf({
			tokens: [
				{ prompt: 2000, completion: 20, usage: { prompt_tokens: 2000, eval_duration: 1e9 } },
				{
					prompt: 318,
					completion: 164,
					usage: {
						prompt_tokens: 318,
						completion_tokens: 164,
						total_tokens: 482,
						load_duration: 420_000_000,
						prompt_eval_duration: 2_850_000_000,
						eval_duration: 2_030_000_000,
						total_duration: 6_300_000_000,
						'response_token/s': 60.7,
						queue_time: 0.02
					}
				}
			]
		});
		expect(usage).toMatchObject({
			input: 2318,
			output: 184,
			total: 482,
			load: 0.42,
			promptEval: 2.85,
			generation: 3.03,
			duration: 6.3,
			attempts: 2,
			extra: [['queue_time', '0.02']]
		});
	});

	it('works with the counts alone, and without anything', () => {
		expect(usageOf({ tokens: [{ prompt: 10, completion: 5 }] })).toMatchObject({
			input: 10,
			output: 5,
			total: 15,
			duration: null
		});
		expect(usageOf({ tokens: [{ prompt: null, completion: null, usage: {} }] })).toBeNull();
		expect(usageOf({})).toBeNull();
	});
});

describe('speed and splitInput', () => {
	it('estimate', () => {
		expect(speed(184, 3.03)).toBeCloseTo(60.73, 1);
		expect(speed(184, 0)).toBeNull();
		expect(splitInput(100, 'a'.repeat(30), 'b'.repeat(70))).toEqual([30, 70]);
		expect(splitInput(100, '', '')).toEqual([0, 100]);
	});
});
