<script lang="ts">
	import { cn } from '#lib/utils.ts';

	// A label whose weight changes with its state (chosen, current) at the width of its bolder
	// weight, so that what stands beside it does not move (web/DESIGN.md, "Steady layout").
	let { text, class: className }: { text: string; class?: string } = $props();
</script>

<span class={cn('steady-weight', className)} data-text={text}
	><span class="truncate">{text}</span></span
>
