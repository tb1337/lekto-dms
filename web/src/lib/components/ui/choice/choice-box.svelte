<script lang="ts" generics="T">
	// The one native checkbox or radio button of the UI. Alone it sits in a row or card that is
	// itself the label; with a text beside it, use `Choice`. A test forbids raw inputs elsewhere.
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
		'size-4 shrink-0 accent-primary outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50',
		type === 'radio' ? 'rounded-full' : 'rounded-xs',
		className
	)}
	{...restProps}
/>
