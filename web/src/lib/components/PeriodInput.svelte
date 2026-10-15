<script lang="ts">
	import { Input } from '#lib/components/ui/input/index.ts';
	import type { Period } from '#lib/fields.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A period: from and to as dates, or a whole month at once, which sets both. One date alone
	// is that day (`toApi`). Each change gives a new value, so it works bound and with
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

	/** `YYYY-MM` while the period is exactly one month, else empty. */
	const month = $derived.by(() => {
		const found = /^(\d{4})-(\d{2})-01$/.exec(value.start);
		return found && value.end === lastDay(Number(found[1]), Number(found[2]))
			? `${found[1]}-${found[2]}`
			: '';
	});

	function lastDay(year: number, month: number): string {
		const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
		return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
	}

	function set(next: Period) {
		value = next;
		onchange?.(next);
	}

	function pickMonth(text: string) {
		const found = /^(\d{4})-(\d{2})$/.exec(text);
		if (!found) return;
		set({ start: `${text}-01`, end: lastDay(Number(found[1]), Number(found[2])) });
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
		{m.field_period_month()}
		<Input
			type="month"
			value={month}
			{disabled}
			aria-label={label ? m.field_period_month_of({ name: label }) : undefined}
			oninput={(event) => pickMonth(event.currentTarget.value)}
		/>
	</label>
</div>
