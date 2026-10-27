<script lang="ts">
	import { untrack } from 'svelte';
	import { Input } from '#lib/components/ui/input/index.ts';
	import type { Period } from '#lib/fields.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { readPeriod, writePeriod } from '#lib/periods.ts';
	import DateInput from '#lib/components/DateInput.svelte';

	// A period: from and to as dates, or in one field as it is written (`2026-Q2`, `KW 17/2026`,
	// `März 2026`, …), which sets both; changed from and to show there in ISO 8601. One date
	// alone is that day (`toApi`). Each change gives a new value, so it works bound and with
	// `onchange` alike. What is written is taken when the field is left or on Enter, not while
	// it is typed (`2026` on the way to `2026-W17` is not the year); `onunreadable` tells the
	// caller while the text cannot be read, so it does not save a value the field does not show.
	// `id` goes to the first input, which the caller labels.
	let {
		value = $bindable(),
		id,
		label,
		invalid = false,
		disabled = false,
		onchange,
		onunreadable
	}: {
		value: Period;
		id?: string;
		label?: string;
		invalid?: boolean;
		disabled?: boolean;
		onchange?: (value: Period) => void;
		onunreadable?: (unreadable: boolean) => void;
	} = $props();

	const errorId = $props.id();
	// What the user types stays while it is the period's (until the field is left, or from or
	// to change); else the field shows the period as written. It is read once, as it is typed
	// (`read`: the period it writes, null if it cannot be read; issue #69).
	let draft = $state<{ text: string; read: Period | null } & Period>({
		text: '',
		read: null,
		start: '',
		end: ''
	});
	let typing = $state(false);
	const typed = $derived(
		typing && draft.start === value.start && draft.end === value.end ? draft.text : null
	);
	const notation = $derived(typed ?? writePeriod(value.start, value.end));
	const unreadable = $derived(typed !== null && typed.trim() !== '' && draft.read === null);

	$effect(() => {
		onunreadable?.(unreadable);
		return () => onunreadable?.(false);
	});

	// A value from outside (the form reset or loaded again) drops what was typed, also when it
	// is the same period: an unreadable text never changes the value (issue #68). The field's
	// own changes keep it (`set`).
	let own = false;
	$effect(() => {
		void value;
		untrack(() => {
			if (own) own = false;
			else typing = false;
		});
	});

	function set(next: Period) {
		own = true;
		value = next;
		onchange?.(next);
	}

	function type(text: string) {
		draft = { text, read: readPeriod(text), start: value.start, end: value.end };
		typing = true;
	}

	/** Takes the typed text as the period; false while it cannot be read. */
	function commit(): boolean {
		const text = typed;
		if (text === null) return true;
		const next = text.trim() === '' ? { start: '', end: '' } : draft.read;
		if (next === null) return false;
		if (next.start !== value.start || next.end !== value.end) set(next);
		draft = { text, read: next, ...next };
		return true;
	}

	function leave() {
		if (commit()) typing = false;
	}

	function keydown(event: KeyboardEvent) {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		commit();
	}
</script>

<div class="grid grid-cols-2 gap-2">
	<label class="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
		{m.field_period_from()}
		<DateInput
			{id}
			class="px-2.5"
			value={value.start}
			{disabled}
			{invalid}
			label={label ? m.field_period_from_of({ name: label }) : m.field_period_from()}
			onchange={(start) => set({ ...value, start })}
		/>
	</label>
	<label class="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
		{m.field_period_to()}
		<DateInput
			class="px-2.5"
			value={value.end}
			{disabled}
			{invalid}
			label={label ? m.field_period_to_of({ name: label }) : m.field_period_to()}
			onchange={(end) => set({ ...value, end })}
		/>
	</label>
	<label class="col-span-2 flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
		{m.field_period_notation()}
		<Input
			value={notation}
			{disabled}
			spellcheck={false}
			autocomplete="off"
			placeholder={m.field_period_placeholder()}
			class="font-mono"
			aria-invalid={unreadable || undefined}
			aria-describedby={unreadable ? errorId : undefined}
			aria-label={label ? m.field_period_notation_of({ name: label }) : undefined}
			oninput={(event) => type(event.currentTarget.value)}
			onkeydown={keydown}
			onblur={leave}
		/>
	</label>
	{#if unreadable}
		<p id={errorId} class="col-span-2 text-xs text-destructive">{m.field_period_unreadable()}</p>
	{/if}
</div>
