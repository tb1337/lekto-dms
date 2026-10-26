<script lang="ts">
	import InfoTip from '#lib/components/InfoTip.svelte';
	import { formatDuration } from '#lib/duration.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { speed, type Usage } from '#lib/usage.ts';

	// The token figures of a model call behind an info icon (`InfoTip`).
	// `pages`: the calls are one per page (the vision model's OCR), not attempts.
	let {
		usage,
		model,
		id,
		pages = false
	}: { usage: Usage; model: string | null; id: string; pages?: boolean } = $props();

	const count = (value: number | null) => (value === null ? '–' : formatNumber(value));
	const seconds = (value: number | null) => (value === null ? '–' : formatDuration(value));
	function timed(duration: number | null, tokens: number | null): string {
		const rate = speed(tokens, duration);
		return rate === null
			? seconds(duration)
			: m.tokens_timed({
					duration: seconds(duration),
					speed: formatNumber(rate, { maximumFractionDigits: 1 })
				});
	}
	// The model, and how often it was asked: once per page, the requests about the document
	// (the proposal and the facts), and the attempts when more than one.
	const heading = $derived(
		[
			model,
			pages ? m.prompt_calls({ count: usage.attempts }) : null,
			!pages && usage.requests > 1 ? m.prompt_requests({ count: usage.requests }) : null,
			!pages && usage.attempts > 1 ? m.prompt_attempts({ count: usage.attempts }) : null
		]
			.filter(Boolean)
			.join(' · ')
	);
	const rows = $derived(
		[
			[m.tokens_input(), count(usage.input)],
			usage.cached === null ? null : [m.tokens_cached(), count(usage.cached)],
			[m.tokens_output(), count(usage.output)],
			[m.tokens_total(), count(usage.total)],
			usage.load === null ? null : [m.tokens_load(), seconds(usage.load)],
			usage.promptEval === null
				? null
				: [m.tokens_prompt_eval(), timed(usage.promptEval, usage.input)],
			usage.generation === null ? null : [m.tokens_eval(), timed(usage.generation, usage.output)],
			usage.duration === null ? null : [m.tokens_duration(), seconds(usage.duration)],
			...usage.extra
		].filter((row): row is [string, string] => row !== null)
	);
</script>

<InfoTip label={m.tokens_details()} {id} class="w-80">
	<p class="mb-1.5 font-semibold">
		{heading}
	</p>
	<dl class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 tabular-nums">
		{#each rows as [name, value], index (index)}
			<dt class="whitespace-nowrap opacity-75">{name}</dt>
			<dd class="text-right">{value}</dd>
		{/each}
	</dl>
</InfoTip>
