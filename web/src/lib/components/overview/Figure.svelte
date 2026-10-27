<script lang="ts">
	import { formatNumber } from '#lib/i18n.ts';

	// The big number of a tile and what it counts.
	let { count, label }: { count: number; label: string } = $props();
</script>

<p class="flex items-baseline gap-2">
	<span class="text-figure tabular-nums">{formatNumber(count)}</span>
	<span class="text-muted-foreground">{label}</span>
</p>
