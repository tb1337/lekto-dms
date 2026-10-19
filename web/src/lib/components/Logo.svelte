<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	let { class: className = '' }: { class?: string } = $props();
</script>

<!-- The wordmark lekto, for now in the typography of the earlier one. -->
<span
	class={cn('font-mono font-medium tracking-tight', className)}
	aria-label={m.app_name()}
	role="img">lekto</span
>
