/**
 * What a language model reported about a call (`output.tokens` of a log entry: per attempt
 * the token counts and the endpoint's whole usage report). Ollama, also through OpenWebUI,
 * reports durations in nanoseconds; other endpoints only the counts.
 */

export interface Usage {
	input: number | null;
	/** Of the input, the tokens the endpoint took from its cache, where it said. */
	cached: number | null;
	output: number | null;
	total: number | null;
	/** Seconds, summed over the attempts; null if the endpoint did not say. */
	load: number | null;
	promptEval: number | null;
	generation: number | null;
	duration: number | null;
	/** Other figures of the report, as it named them. */
	extra: [string, string][];
	attempts: number;
}

const KNOWN = new Set([
	'prompt_tokens',
	// Shown as `cached` (the log reads them from either report).
	'cache_read_input_tokens',
	'completion_tokens',
	'total_tokens',
	'prompt_eval_count',
	'eval_count',
	'load_duration',
	'prompt_eval_duration',
	'eval_duration',
	'total_duration',
	'prompt_token/s',
	'response_token/s',
	'approximate_total'
]);

type Attempt = { prompt?: unknown; completion?: unknown; cached?: unknown; usage?: unknown };

function number(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function sum(values: (number | null)[]): number | null {
	const known = values.filter((value): value is number => value !== null);
	return known.length === 0 ? null : known.reduce((total, value) => total + value, 0);
}

/** The usage of a log entry's output, summed over its attempts; null without any. */
export function usageOf(output: Record<string, unknown>): Usage | null {
	const tokens = output.tokens;
	if (!Array.isArray(tokens) || tokens.length === 0) return null;
	const attempts = tokens as Attempt[];
	const reports = attempts.map((attempt) =>
		attempt.usage && typeof attempt.usage === 'object'
			? (attempt.usage as Record<string, unknown>)
			: {}
	);
	const seconds = (key: string) =>
		sum(
			reports.map((report) => (number(report[key]) === null ? null : (report[key] as number) / 1e9))
		);
	const input = sum(attempts.map((attempt) => number(attempt.prompt)));
	const cached = sum(attempts.map((attempt) => number(attempt.cached)));
	const output_ = sum(attempts.map((attempt) => number(attempt.completion)));
	const reported = sum(reports.map((report) => number(report.total_tokens)));
	// Other figures, one per name: numbers summed over the attempts, texts the last one.
	const others = new Map<string, number | string>();
	for (const report of reports) {
		for (const [key, value] of Object.entries(report)) {
			if (KNOWN.has(key) || (typeof value !== 'number' && typeof value !== 'string')) continue;
			const before = others.get(key);
			others.set(
				key,
				typeof value === 'number' && typeof before === 'number' ? before + value : value
			);
		}
	}
	const extra: [string, string][] = [...others].map(([key, value]) => [key, String(value)]);
	const usage: Usage = {
		input,
		cached,
		output: output_,
		total: reported ?? (input !== null || output_ !== null ? (input ?? 0) + (output_ ?? 0) : null),
		load: seconds('load_duration'),
		promptEval: seconds('prompt_eval_duration'),
		generation: seconds('eval_duration'),
		duration: seconds('total_duration'),
		extra,
		attempts: attempts.length
	};
	const empty = [usage.input, usage.output, usage.total, usage.duration].every(
		(value) => value === null
	);
	return empty && extra.length === 0 ? null : usage;
}

/** Tokens per second, or null if either is unknown or the time is zero. */
export function speed(tokens: number | null, seconds: number | null): number | null {
	return tokens === null || seconds === null || seconds <= 0 ? null : tokens / seconds;
}

/**
 * The input tokens of the messages of a call (system, document, task, …): the endpoint counts
 * them together, so they are split by characters, an estimate. Without characters the last
 * part has them all; the shares add up to `input`.
 */
export function splitInput(input: number, parts: readonly string[]): number[] {
	const characters = parts.reduce((total, part) => total + part.length, 0);
	if (characters === 0) return parts.map((_, index) => (index === parts.length - 1 ? input : 0));
	let left = input;
	return parts.map((part, index) => {
		if (index === parts.length - 1) return left;
		const share = Math.round((input * part.length) / characters);
		left -= share;
		return share;
	});
}
