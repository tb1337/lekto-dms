import { describe, expect, it } from 'vitest';
import { speed, splitInput, usageOf } from './usage.ts';

describe('usageOf', () => {
	it('sums the attempts and reads the durations of Ollama', () => {
		const usage = usageOf({
			tokens: [
				{
					prompt: 2000,
					completion: 20,
					usage: { prompt_tokens: 2000, eval_duration: 1e9, queue_time: 0.01 }
				},
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
			extra: [['queue_time', '0.03']]
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

describe('a further request about the document', () => {
	it('counts as a request, not as another attempt, and its tokens add up', () => {
		const usage = usageOf({
			tokens: [
				{ prompt: 2400, completion: 80, usage: {} },
				{ prompt: 2500, completion: 30, cached: 2300, request: 'facts', usage: {} }
			]
		});
		expect(usage).toMatchObject({ input: 4900, cached: 2300, attempts: 1, requests: 2 });
	});
});

describe('tokens from a cache', () => {
	it('sums what the endpoints took from their cache, where they said', () => {
		const tokens = [
			{ prompt: 2400, completion: 10, cached: 2048, usage: {} },
			{ prompt: 2450, completion: 12, cached: 2400, usage: {} }
		];
		expect(usageOf({ tokens })?.cached).toBe(4448);
		expect(usageOf({ tokens: [{ prompt: 5, completion: 1, usage: {} }] })?.cached).toBeNull();
		// LiteLLM's own figure for Anthropic is that same number: not a second row.
		const anthropic = [
			{ prompt: 9, completion: 1, cached: 7, usage: { cache_read_input_tokens: 7 } }
		];
		expect(usageOf({ tokens: anthropic })?.extra).toEqual([]);
	});
});

describe('speed and splitInput', () => {
	it('estimate', () => {
		expect(speed(184, 3.03)).toBeCloseTo(60.73, 1);
		expect(speed(184, 0)).toBeNull();
		expect(splitInput(100, ['a'.repeat(30), 'b'.repeat(70)])).toEqual([30, 70]);
		expect(splitInput(100, ['', ''])).toEqual([0, 100]);
		expect(splitInput(10, ['a', 'b', 'c'])).toEqual([3, 3, 4]);
	});
});
