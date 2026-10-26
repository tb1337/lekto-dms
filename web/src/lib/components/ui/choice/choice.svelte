<script lang="ts" generics="T">
	// A checkbox or radio button with its text: only the box and the text take the click, not the
	// space beside them, even where a parent stretches its children (a `Field`: `max-w-fit`). The
	// box sits on the first line of the text whatever its line height.
	import type { ComponentProps, Snippet } from 'svelte';
	import { cn } from '#lib/utils.ts';
	import ChoiceBox from './choice-box.svelte';

	type Props = Omit<ComponentProps<typeof ChoiceBox<T>>, 'class'> & {
		class?: string;
		children: Snippet;
	};

	let {
		checked = $bindable(false),
		group = $bindable(),
		class: className,
		children,
		...restProps
	}: Props = $props();
</script>

<label
	data-slot="choice"
	class={cn(
		'flex w-fit max-w-fit cursor-pointer items-start gap-2 text-sm has-disabled:cursor-not-allowed has-disabled:opacity-50',
		className
	)}
>
	<ChoiceBox bind:checked bind:group class="mt-[calc((1lh-1rem)/2)]" {...restProps} />
	{@render children()}
</label>
