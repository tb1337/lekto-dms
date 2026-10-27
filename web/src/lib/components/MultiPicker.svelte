<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { matchesWords, searchWords, toggled } from '#lib/picking.ts';
	import { cn } from '#lib/utils.ts';
	import { ChoiceBox } from '#lib/components/ui/choice/index.ts';
	import Chip from '#lib/components/Chip.svelte';
	import SearchField from '#lib/components/SearchField.svelte';

	export interface PickerOption {
		value: string;
		label: string;
	}

	// Several values from a list: chosen ones as chips, the rest as checkboxes with a filter.
	// Chosen values missing from the list (deleted, no longer visible) stay until removed.
	let {
		options,
		selected,
		onchange,
		label,
		invalid = false,
		id
	}: {
		options: readonly PickerOption[];
		selected: readonly string[];
		onchange: (selected: string[]) => void;
		label: string;
		invalid?: boolean;
		id?: string;
	} = $props();

	let query = $state('');
	const labelOf = (value: string) =>
		options.find((option) => option.value === value)?.label ?? m.rule_unknown();
	// The API keeps repeated values of a list; they show as one chip and go together.
	const chips = $derived([...new Set(selected)]);
	const words = $derived(searchWords(query));
	const shown = $derived(options.filter((option) => matchesWords(option.label, words)));

	function toggle(value: string, on: boolean) {
		onchange(toggled(selected, value, on));
	}
</script>

<div
	{id}
	role="group"
	aria-label={label}
	class={cn(
		'flex min-w-0 flex-col gap-2 rounded-xl border border-input bg-card p-2 dark:bg-input/30',
		invalid && 'border-destructive'
	)}
>
	<div class="flex flex-wrap gap-1.5">
		{#each chips as value (value)}
			<Chip
				removeLabel={m.rule_remove_value({ name: labelOf(value) })}
				onremove={() => toggle(value, false)}>{labelOf(value)}</Chip
			>
		{:else}
			<span class="px-1 text-sm text-muted-foreground">{m.rule_nothing_chosen()}</span>
		{/each}
	</div>
	{#if options.length > 6}
		<SearchField bind:value={query} label={m.rule_filter()} />
	{/if}
	<ul class="flex max-h-44 flex-col overflow-y-auto">
		{#each shown as option (option.value)}
			<li>
				<label
					class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-secondary"
				>
					<ChoiceBox
						checked={selected.includes(option.value)}
						onchange={(event) => toggle(option.value, event.currentTarget.checked)}
					/>
					{option.label}
				</label>
			</li>
		{/each}
	</ul>
</div>
