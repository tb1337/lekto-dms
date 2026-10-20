<script lang="ts">
	import Clock from '@lucide/svelte/icons/clock';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { dueText, type CardLine, type Due } from '#lib/card-fields.ts';
	import { formatDate } from '#lib/i18n.ts';

	// The fields a lens shows on a card (`card-fields.ts`): an amount with its deadline on one
	// line, the others as name and value. The deadline says how soon in words, red with a
	// warning once passed, yellow with a clock within seven days; the day in its tooltip. In a
	// narrow card what does not fit wraps rather than being cut.
	let { lines }: { lines: readonly CardLine[] } = $props();
</script>

{#snippet deadline(due: Due, name: string)}
	<span
		class={[
			'inline-flex shrink-0 items-center gap-1 tabular-nums',
			due.state === 'overdue' && 'font-semibold text-lane-red-foreground',
			due.state === 'soon' && 'font-semibold text-lane-yellow-foreground',
			due.state === 'later' && 'text-muted-foreground'
		]}
		title="{name}: {formatDate(due.day)}"
	>
		{#if due.state === 'overdue'}
			<TriangleAlert class="size-3.5" aria-hidden="true" />
		{:else if due.state === 'soon'}
			<Clock class="size-3.5" aria-hidden="true" />
		{/if}
		<span class="sr-only">{name}:</span>
		{dueText(due)}
	</span>
{/snippet}

{#if lines.length > 0}
	<div class="flex min-w-0 flex-col gap-1 text-sm">
		{#each lines as line, index (index)}
			{#if line.kind === 'pay'}
				<div class="flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
					<span class="font-semibold tabular-nums">{line.amount ?? ''}</span>
					{#if line.due}{@render deadline(line.due, line.dueName)}{/if}
				</div>
			{:else}
				<div class="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
					<span class="text-muted-foreground">{line.name}</span>
					{#if line.due}
						{@render deadline(line.due, line.name)}
					{:else}
						<span class="ml-auto min-w-0 text-right break-words tabular-nums">{line.text}</span>
					{/if}
				</div>
			{/if}
		{/each}
	</div>
{/if}
