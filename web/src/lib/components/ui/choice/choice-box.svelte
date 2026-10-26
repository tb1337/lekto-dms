<script lang="ts" generics="T">
	// The one checkbox or radio button of the UI: a native input (keyboard, forms), drawn from the
	// tokens. Alone it sits in a row or card that is itself the label; with a text beside it, use
	// `Choice`. A test forbids raw inputs elsewhere.
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { cn } from '#lib/utils.ts';

	type Props = Omit<HTMLInputAttributes, 'type' | 'checked' | 'group' | 'value'> & {
		type?: 'checkbox' | 'radio';
		checked?: boolean;
		/** The chosen value of a radio group, or the chosen values of a checkbox group. */
		group?: T | T[];
		/** This box's value within `group`. */
		value?: T;
	};

	let {
		type = 'checkbox',
		checked = $bindable(false),
		group = $bindable(),
		value,
		class: className,
		onchange,
		...restProps
	}: Props = $props();

	const isChecked = $derived(
		group === undefined
			? checked
			: type === 'radio'
				? group === value
				: Array.isArray(group) && group.includes(value as T)
	);

	function change(event: Event & { currentTarget: HTMLInputElement }): void {
		const on = event.currentTarget.checked;
		if (group === undefined) {
			checked = on;
		} else if (type === 'radio') {
			group = value;
		} else {
			const chosen = Array.isArray(group) ? group : [];
			group = on
				? chosen.includes(value as T)
					? chosen
					: [...chosen, value as T]
				: chosen.filter((item) => item !== value);
		}
		onchange?.(event);
	}
</script>

<input
	{type}
	checked={isChecked}
	value={typeof value === 'string' ? value : undefined}
	onchange={change}
	data-slot="choice-box"
	class={cn(
		// Drawn from the tokens, not by the system (web/DESIGN.md, "Checkboxes"): the frame of the
		// fields, filled with the primary colour when chosen, a tick or a dot drawn by CSS.
		'relative grid size-4 shrink-0 cursor-pointer appearance-none place-content-center border border-input bg-card transition-colors outline-none after:absolute after:-inset-1 checked:border-primary checked:bg-primary focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 max-sm:after:-inset-3.5 dark:bg-input/30 dark:checked:bg-primary',
		type === 'radio'
			? 'rounded-full checked:before:size-1.5 checked:before:rounded-full checked:before:bg-primary-foreground'
			: 'rounded-xs checked:before:h-[9px] checked:before:w-[5px] checked:before:-translate-y-px checked:before:rotate-45 checked:before:border-r-2 checked:before:border-b-2 checked:before:border-primary-foreground',
		className
	)}
	{...restProps}
/>
