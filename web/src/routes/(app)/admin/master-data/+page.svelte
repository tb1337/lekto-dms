<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { page } from '$app/state';
	import FieldsPanel from '#lib/components/FieldsPanel.svelte';
	import IdentifiersPanel from '#lib/components/IdentifiersPanel.svelte';
	import MasterDataList from '#lib/components/MasterDataList.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import TagsPanel from '#lib/components/TagsPanel.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { MASTER_TABS as TABS, masterTabOf, type MasterTab as Tab } from '#lib/master-tabs.ts';
	import { kindFilter } from '#lib/tag-kinds.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import SearchField from '#lib/components/SearchField.svelte';
	import IconButton from '#lib/components/IconButton.svelte';

	// Five tabs: contacts, document types, every kind of tag, fields, and the identifiers no
	// person has confirmed (Tobi, 27.10.2026). The tab stands in the URL (an unknown one is the
	// first); the API refuses everyone but admins. Each tab has its own search (in this browser);
	// all but the identifiers add with the button level with the title (on a phone an icon
	// button).
	const tab = $derived(masterTabOf(page.url.searchParams));
	const queries = $state<Record<Tab, string>>({
		contacts: '',
		'document-types': '',
		tags: '',
		fields: '',
		identifiers: ''
	});
	const ADD: Record<Exclude<Tab, 'identifiers'>, () => string> = {
		contacts: m.master_add_contact,
		'document-types': m.master_add_type,
		tags: m.master_add_tag,
		fields: m.master_add_field
	};
	const SEARCH: Record<Tab, () => string> = {
		contacts: m.master_search_contacts,
		'document-types': m.master_search_types,
		tags: m.master_search_tags,
		fields: m.master_search_fields,
		identifiers: m.master_search_identifiers
	};
	const LABEL: Record<Tab, () => string> = {
		contacts: m.master_contacts,
		'document-types': m.master_types,
		tags: m.master_tags,
		fields: m.master_fields,
		identifiers: m.master_identifiers
	};

	/** A new item of the tab; on the Tags tab of the kind it shows, else the kind comes first. */
	function add() {
		if (tab === 'identifiers') return;
		if (tab === 'tags') masterDataDialogs.open(kindFilter(page.url.searchParams) ?? 'any-tag');
		else masterDataDialogs.open(tab);
	}
</script>

<svelte:head><title>{m.nav_master_data()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-4 sm:gap-6">
	<PageHeader title={m.nav_master_data()}>
		{#snippet actions()}
			{#if tab === 'identifiers'}
				<!-- Identifiers are confirmed, not created here. -->
			{:else if session.isAdmin && phone.current}
				<IconButton label={ADD[tab]()} variant="default" onclick={add}>
					<Plus aria-hidden="true" />
				</IconButton>
			{:else if session.isAdmin}
				<Button onclick={add}>
					<Plus aria-hidden="true" />
					{ADD[tab]()}
				</Button>
			{/if}
		{/snippet}
	</PageHeader>

	{#if !session.isAdmin}
		<p class="text-muted-foreground">{m.admin_only()}</p>
	{:else}
		<div>
			<!-- Five equal tabs on a phone, a shorter name for the types. -->
			<TabBar
				label={m.nav_master_data()}
				tabs={TABS.map((value) => ({
					key: value,
					href: `?tab=${value}`,
					label:
						value === 'document-types' && phone.current ? m.master_types_short() : LABEL[value]()
				}))}
				current={tab}
				fill
			/>
			<div class="mt-4 flex flex-col gap-3 sm:gap-4">
				<SearchField
					bind:value={queries[tab]}
					label={m.master_search_label({ what: LABEL[tab]() })}
					placeholder={SEARCH[tab]()}
				/>
				{#key tab}
					{#if tab === 'fields'}
						<FieldsPanel query={queries.fields} />
					{:else if tab === 'identifiers'}
						<IdentifiersPanel query={queries.identifiers} />
					{:else if tab === 'tags'}
						<TagsPanel query={queries.tags} />
					{:else}
						<MasterDataList kind={tab} query={queries[tab]} />
					{/if}
				{/key}
			</div>
		</div>
	{/if}
</div>
