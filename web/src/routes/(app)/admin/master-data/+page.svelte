<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import FieldsPanel from '#lib/components/FieldsPanel.svelte';
	import MasterDataList from '#lib/components/MasterDataList.svelte';
	import TagTreeList from '#lib/components/TagTreeList.svelte';
	import { isTagKind } from '#lib/masterdata-api.ts';
	import * as Tabs from '#lib/components/ui/tabs/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';

	const TABS = [
		'contacts',
		'document-types',
		'tags',
		'contact-groups',
		'type-groups',
		'fields'
	] as const;
	type Tab = (typeof TABS)[number];

	// The tab stands in the URL; the API refuses everyone but admins.
	const tab = $derived<Tab>(
		(TABS as readonly string[]).includes(page.url.searchParams.get('tab') ?? '')
			? (page.url.searchParams.get('tab') as Tab)
			: 'contacts'
	);
</script>

<svelte:head><title>{m.nav_master_data()} · p:api:q</title></svelte:head>

<div class="flex flex-col gap-6">
	<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_master_data()}</h1>

	{#if !session.isAdmin}
		<p class="text-muted-foreground">{m.admin_only()}</p>
	{:else}
		<Tabs.Root value={tab} onValueChange={(value) => goto(`?tab=${value}`, { reset: false })}>
			<!-- Six tabs: on a narrow screen they wrap instead of running off the page. -->
			<Tabs.List
				class="h-auto flex-wrap justify-start group-data-[orientation=horizontal]/tabs:h-auto"
			>
				<Tabs.Trigger value="contacts">{m.master_contacts()}</Tabs.Trigger>
				<Tabs.Trigger value="document-types">{m.master_types()}</Tabs.Trigger>
				<Tabs.Trigger value="tags">{m.master_document_tags()}</Tabs.Trigger>
				<Tabs.Trigger value="contact-groups">{m.master_contact_groups()}</Tabs.Trigger>
				<Tabs.Trigger value="type-groups">{m.master_type_groups()}</Tabs.Trigger>
				<Tabs.Trigger value="fields">{m.master_fields()}</Tabs.Trigger>
			</Tabs.List>
			<div class="mt-4">
				{#key tab}
					{#if tab === 'fields'}
						<FieldsPanel />
					{:else if isTagKind(tab)}
						<TagTreeList kind={tab} />
					{:else}
						<MasterDataList kind={tab} />
					{/if}
				{/key}
			</div>
		</Tabs.Root>
	{/if}
</div>
