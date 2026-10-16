<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { speed, type Usage } from '#lib/usage.ts';

	// The token figures of a model call behind an info icon: on hover, on focus, on a tap.
	// `pages`: the calls are one per page (the vision model's OCR), not attempts.
	let {
		usage,
		model,
		id,
		pages = false
	}: { usage: Usage; model: string | null; id: string; pages?: boolean } = $props();

	let open = $state(false);

	const count = (value: number | null) => (value === null ? '–' : formatNumber(value));
	const seconds = (value: number | null) =>
		value === null
			? '–'
			: formatNumber(value, {
					style: 'unit',
					unit: 'second',
					unitDisplay: 'narrow',
					maximumFractionDigits: 2
				});
	function timed(duration: number | null, tokens: number | null): string {
		const rate = speed(tokens, duration);
		return rate === null
			? seconds(duration)
			: m.tokens_timed({
					duration: seconds(duration),
					speed: formatNumber(rate, { maximumFractionDigits: 1 })
				});
	}
	const rows = $derived(
		[
			[m.tokens_input(), count(usage.input)],
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

<span class="relative inline-flex">
	<button
		type="button"
		aria-label={m.tokens_details()}
		aria-describedby={open ? id : undefined}
		aria-expanded={open}
		onmouseenter={() => (open = true)}
		onmouseleave={() => (open = false)}
		onfocus={() => (open = true)}
		onblur={() => (open = false)}
		onclick={() => (open = !open)}
		onkeydown={(event) => event.key === 'Escape' && (open = false)}
		class="grid size-7 place-items-center rounded-full text-muted-foreground hover:text-foreground"
	>
		<Info class="size-4" aria-hidden="true" />
	</button>
	{#if open}
		<div
			{id}
			role="tooltip"
			class="absolute top-full left-1/2 z-20 mt-1.5 w-80 -translate-x-1/2 rounded-xl bg-foreground px-3.5 py-3 text-[12.5px] leading-normal text-background shadow-lg"
		>
			<p class="mb-1.5 font-semibold">
				{model ?? ''}{#if pages}
					· {m.prompt_calls({ count: usage.attempts })}{:else if usage.attempts > 1}
					· {m.prompt_attempts({ count: usage.attempts })}{/if}
			</p>
			<dl class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 tabular-nums">
				{#each rows as [name, value], index (index)}
					<dt class="whitespace-nowrap opacity-75">{name}</dt>
					<dd class="text-right">{value}</dd>
				{/each}
			</dl>
		</div>
	{/if}
</span>
