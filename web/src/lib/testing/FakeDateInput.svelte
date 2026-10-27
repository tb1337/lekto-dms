<script lang="ts">
	// `DateInput` in component tests: jsdom has no layout for the date picker's segments, so a
	// plain date input stands in, with the same props (`tests/setup.ts`).
	let {
		value = $bindable(''),
		id,
		label,
		min,
		max,
		disabled = false,
		invalid = false,
		class: className,
		onchange
	}: {
		value?: string;
		id?: string;
		label: string;
		min?: string;
		max?: string;
		disabled?: boolean;
		invalid?: boolean;
		class?: string;
		onchange?: (value: string) => void;
	} = $props();
</script>

<input
	{id}
	class={className}
	type="date"
	aria-label={label}
	aria-invalid={invalid || undefined}
	{min}
	{max}
	{disabled}
	bind:value
	oninput={(event) => onchange?.(event.currentTarget.value)}
/>
