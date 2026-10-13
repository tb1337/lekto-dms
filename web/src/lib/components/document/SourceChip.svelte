<script lang="ts">
	import type { Place } from '#lib/document-view.ts';
	import { m } from '#lib/paraglide/messages.js';

	// Where a quote stands: the page, a click shows the passage in the viewer.
	let { place, onjump }: { place: Place; onjump: (place: Place) => void } = $props();
</script>

<button
	type="button"
	onclick={() => onjump(place)}
	aria-label={m.source_jump({ page: place.page })}
	class="shrink-0 rounded-full bg-panel px-2 font-mono text-[11px] leading-5 text-brand hover:underline"
>
	{m.source_page({ page: place.page })}
</button>
