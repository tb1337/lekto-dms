<script lang="ts">
	import { Tooltip as TooltipPrimitive } from 'bits-ui';

	// A tooltip with its own provider, so that it works wherever it stands (a page, a dialog, a
	// component test); bits-ui shares the delay among the providers of a page.
	let {
		open = $bindable(false),
		delayDuration = 300,
		...restProps
	}: TooltipPrimitive.RootProps & { delayDuration?: number } = $props();
</script>

<TooltipPrimitive.Provider {delayDuration}>
	<TooltipPrimitive.Root bind:open {...restProps} />
</TooltipPrimitive.Provider>
