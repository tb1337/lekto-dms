<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// "Loading …" where a page or panel waits for its data (web/DESIGN.md, "States"); a status
	// that screen readers announce.
	let { class: className = '' }: { class?: string } = $props();
</script>

<p class={cn('text-muted-foreground', className)} role="status">{m.loading()}</p>
