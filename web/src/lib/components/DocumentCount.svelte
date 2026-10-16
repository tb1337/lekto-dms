<script lang="ts">
	import FileText from '@lucide/svelte/icons/file-text';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	// How many documents (in the scope setting) carry an item of master data: a link to the
	// document view, filtered by it; none, plain.
	let { count, href }: { count: number | null | undefined; href: string } = $props();
	const label = $derived(
		count === 1 ? m.master_documents_one() : m.master_documents({ count: formatNumber(count ?? 0) })
	);
</script>

{#if count === null || count === undefined}
	<span class="w-24" aria-hidden="true"></span>
{:else if count === 0}
	<span class="shrink-0 px-2 text-sm text-muted-foreground tabular-nums">{label}</span>
{:else}
	<a
		{href}
		class="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-sm text-brand tabular-nums hover:bg-panel hover:underline"
	>
		<FileText class="size-3.5" aria-hidden="true" />
		{label}
	</a>
{/if}
