<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { tick } from 'svelte';
	import { addChips } from '#lib/chips.ts';
	import { m } from '#lib/paraglide/messages.js';
	import Chip from '#lib/components/Chip.svelte';

	// Values as chips in a field (a contact's other spellings; Tobi, 20.10.2026): each with its
	// ✕, then a dashed chip that turns into a small input. Enter adds what was typed and stays for
	// the next, leaving the input adds it too; pasted lines become one chip each; a value there
	// already (in any case) is not added again; Escape leaves the input and not the dialog.
	let {
		values = $bindable([]),
		labelledby,
		describedby,
		addLabel,
		inputLabel
	}: {
		values?: string[];
		labelledby?: string;
		describedby?: string;
		/** The dashed chip ("Spelling"). */
		addLabel: string;
		/** The input's name and placeholder ("New spelling"). */
		inputLabel: string;
	} = $props();

	let adding = $state(false);
	let draft = $state('');
	let input = $state<HTMLInputElement | null>(null);

	async function start() {
		adding = true;
		await tick();
		input?.focus();
	}

	function commit() {
		values = addChips(values, draft);
		draft = '';
	}

	function keydown(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			// Not the editor's form: Enter adds the chip.
			event.preventDefault();
			commit();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			draft = '';
			adding = false;
		}
	}

	function paste(event: ClipboardEvent) {
		const text = event.clipboardData?.getData('text') ?? '';
		if (!text.includes('\n')) return;
		event.preventDefault();
		values = addChips(values, `${draft}${text}`);
		draft = '';
	}
</script>

<div
	role="group"
	aria-labelledby={labelledby}
	aria-describedby={describedby}
	class="flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-input bg-card p-2 dark:bg-input/30"
>
	{#each values as value, index (index)}
		<Chip
			removeLabel={m.alias_remove({ name: value })}
			onremove={() => (values = values.filter((_, other) => other !== index))}>{value}</Chip
		>
	{/each}
	{#if adding}
		<input
			bind:this={input}
			bind:value={draft}
			aria-label={inputLabel}
			placeholder={inputLabel}
			maxlength={200}
			class="h-8 w-52 max-w-full rounded-full border border-ring bg-card px-3 text-base outline-none sm:text-sm"
			onkeydown={keydown}
			onpaste={paste}
			onblur={() => {
				commit();
				adding = false;
			}}
		/>
	{:else}
		<Chip variant="add" onclick={start}>
			{#snippet icon()}<Plus class="size-4 shrink-0" aria-hidden="true" />{/snippet}
			{addLabel}
		</Chip>
	{/if}
</div>
