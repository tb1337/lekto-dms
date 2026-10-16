<script lang="ts">
	import { Input } from '#lib/components/ui/input/index.ts';
	import type { Period } from '#lib/fields.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { readPeriod, writePeriod } from '#lib/periods.ts';

	// A period: from and to as dates, or in one field as it is written (`2026-Q2`, `KW 17/2026`,
	// `März 2026`, …), which sets both; changed from and to show there in ISO 8601. One date
	// alone is that day (`toApi`). Each change gives a new value, so it works bound and with
	// `onchange` alike. `id` goes to the first input, which the caller labels.
	let {
		value = $bindable(),
		id,
		label,
		invalid = false,
		disabled = false,
		onchange
	}: {
		value: Period;
		id?: string;
		label?: string;
		invalid?: boolean;
		disabled?: boolean;
		onchange?: (value: Period) => void;
	} = $props();

	const errorId = $props.id();
	// What the user types stays while it is the period's (until the field is left, or from or
	// to change); else the field shows the period as written.
	let draft = $state<{ text: string } & Period>({ text: '', start: '', end: '' });
	let typing = $state(false);
	const typed = $derived(
		typing && draft.start === value.start && draft.end === value.end ? draft.text : null
	);
	const notation = $derived(typed ?? writePeriod(value.start, value.end));
	const unreadable = $derived(typed !== null && typed.trim() !== '' && readPeriod(typed) === null);

	function set(next: Period) {
		value = next;
		onchange?.(next);
	}

	function type(text: string) {
		const next = text.trim() === '' ? { start: '', end: '' } : readPeriod(text);
		if (next) set(next);
		draft = { text, start: value.start, end: value.end };
		typing = true;
	}

	function leave() {
		if (!unreadable) typing = false;
	}
</script>

<div class="grid grid-cols-2 gap-2">
	<label class="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
		{m.field_period_from()}
		<Input
			{id}
			type="date"
			class="px-2.5"
			value={value.start}
			{disabled}
			aria-invalid={invalid || undefined}
			aria-label={label ? m.field_period_from_of({ name: label }) : undefined}
			oninput={(event) => set({ ...value, start: event.currentTarget.value })}
		/>
	</label>
	<label class="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
		{m.field_period_to()}
		<Input
			type="date"
			class="px-2.5"
			value={value.end}
			{disabled}
			aria-invalid={invalid || undefined}
			aria-label={label ? m.field_period_to_of({ name: label }) : undefined}
			oninput={(event) => set({ ...value, end: event.currentTarget.value })}
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
			onblur={leave}
		/>
	</label>
	{#if unreadable}
		<p id={errorId} class="col-span-2 text-xs text-destructive">{m.field_period_unreadable()}</p>
	{/if}
</div>
