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
	class="relative shrink-0 rounded-full bg-panel px-2 font-mono text-micro leading-5 text-brand after:absolute after:-inset-x-1 after:-inset-y-3 hover:underline sm:after:-inset-y-1"
>
	{m.source_page({ page: place.page })}
</button>
