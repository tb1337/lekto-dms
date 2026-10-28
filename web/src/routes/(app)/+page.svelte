<script lang="ts">
	import ExpectedSection from '#lib/components/overview/ExpectedSection.svelte';
	import IdentifiersTile from '#lib/components/overview/IdentifiersTile.svelte';
	import InboxTile from '#lib/components/overview/InboxTile.svelte';
	import SystemTile from '#lib/components/overview/SystemTile.svelte';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// The overview, the start page under the logo (Tobi, 27.10.2026): what waits for someone, each
	// with the way there. The inbox, the open identifiers (admins: they keep the master data), the
	// jobs, and below what is expected (the page "Erwartet" went into it).
</script>

<svelte:head><title>{m.overview_title()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader title={m.overview_title()} subtitle={m.overview_subtitle()} />
	<div class={cn('grid gap-4 sm:grid-cols-2', session.isAdmin && 'lg:grid-cols-3')}>
		<InboxTile />
		{#if session.isAdmin}<IdentifiersTile />{/if}
		<SystemTile />
	</div>
	<ExpectedSection />
</div>
