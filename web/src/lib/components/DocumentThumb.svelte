<script lang="ts">
	import FileText from '@lucide/svelte/icons/file-text';

	// The preview of the first page. A document without page images (still being processed, or
	// failed before they were rendered) has none: the placeholder stands in, and nothing is
	// asked for that cannot be there.
	let {
		id,
		pages,
		class: className = ''
	}: { id: string; pages: number | null; class?: string } = $props();
	let missing = $state(false);
</script>

{#if missing || !pages}
	<div class="grid place-items-center bg-secondary text-muted-foreground {className}">
		<FileText class="size-6" aria-hidden="true" />
	</div>
{:else}
	<img
		src="/api/v1/documents/{id}/preview"
		alt=""
		loading="lazy"
		onerror={() => (missing = true)}
		class="bg-white object-cover object-top {className}"
	/>
{/if}
