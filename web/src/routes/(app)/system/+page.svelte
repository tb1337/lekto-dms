<script lang="ts">
	import { page } from '$app/state';
	import AutomationTab from '#lib/components/system/AutomationTab.svelte';
	import ClassifierTab from '#lib/components/system/ClassifierTab.svelte';
	import JobsTab from '#lib/components/system/JobsTab.svelte';
	import MaintenanceTab from '#lib/components/system/MaintenanceTab.svelte';
	import SearchTab from '#lib/components/system/SearchTab.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { SYSTEM_TABS, systemTab, type SystemTab } from '#lib/system.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';

	// The page "System" (Tobi, 24.10.2026): what Lekto does by itself, for every user; acting
	// on it (training, trying jobs again, the maintenance) is for admins. The tab stands in the URL.
	const tab = $derived(systemTab(page.url.searchParams));
	const LABELS: Record<SystemTab, () => string> = {
		automation: m.system_tab_automation,
		classifier: m.system_tab_classifier,
		search: m.system_tab_search,
		jobs: m.system_tab_jobs,
		maintenance: m.system_tab_maintenance
	};
</script>

<svelte:head><title>{LABELS[tab]()} · {m.nav_system()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-4 sm:gap-6">
	<PageHeader title={m.nav_system()} />
	<TabBar
		label={m.system_tabs()}
		tabs={SYSTEM_TABS.map((value) => ({
			key: value,
			href: `?tab=${value}`,
			label: LABELS[value]()
		}))}
		current={tab}
	/>
	{#key tab}
		{#if tab === 'jobs'}
			<JobsTab />
		{:else if tab === 'maintenance'}
			<MaintenanceTab />
		{:else if tab === 'search'}
			<SearchTab />
		{:else if tab === 'classifier'}
			<ClassifierTab />
		{:else}
			<AutomationTab />
		{/if}
	{/key}
</div>
