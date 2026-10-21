<script lang="ts">
	import { cn } from '#lib/utils.ts';
	import { Command as CommandPrimitive } from 'bits-ui';

	export type CommandRootApi = CommandPrimitive.Root;

	// No scroll to the first item as the list mounts: in a popover the list is not placed yet
	// and stands at the top of the page, so the page jumped there (a phone, Tobi 20.10.2026).
	// The first item is at the top of the list anyway; arrows and typing still scroll.

	let {
		api = $bindable(null),
		ref = $bindable(null),
		value = $bindable(''),
		class: className,
		disableInitialScroll = true,
		...restProps
	}: CommandPrimitive.RootProps & {
		api?: CommandRootApi | null;
	} = $props();
</script>

<CommandPrimitive.Root
	bind:this={api}
	bind:value
	bind:ref
	{disableInitialScroll}
	data-slot="command"
	class={cn(
		'flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground',
		className
	)}
	{...restProps}
/>
