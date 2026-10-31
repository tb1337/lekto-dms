<script lang="ts">
	import { Tooltip as TooltipPrimitive } from 'bits-ui';
	import { hideTip, mayOpenTip, showTip, warm } from '#lib/tips.svelte.ts';

	// A tooltip with its own provider, so that it works wherever it stands (a page, a dialog, a
	// component test). One box of help at a time (`tips.svelte.ts`): opening closes the one shown
	// before; while one shows or just showed, this one skips its delay. A focus opens it only
	// when Tab brought it, not when a dialog or the Beam hands it back.
	let {
		open = $bindable(false),
		delayDuration = 300,
		...restProps
	}: TooltipPrimitive.RootProps & { delayDuration?: number } = $props();

	const tip = { close: () => (open = false) };

	function change(next: boolean) {
		if (next && !mayOpenTip()) return;
		open = next;
	}

	$effect(() => {
		if (open) showTip(tip);
		else hideTip(tip);
	});
	$effect(() => () => hideTip(tip));
</script>

<TooltipPrimitive.Provider delayDuration={warm() ? 0 : delayDuration}>
	<TooltipPrimitive.Root bind:open={() => open, change} {...restProps} />
</TooltipPrimitive.Provider>
