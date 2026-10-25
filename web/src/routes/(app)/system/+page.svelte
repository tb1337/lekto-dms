<script lang="ts">
	import { page } from '$app/state';
	import ClassifierTab from '#lib/components/system/ClassifierTab.svelte';
	import JobsTab from '#lib/components/system/JobsTab.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import { SYSTEM_TABS, systemTab, type SystemTab } from '#lib/system.ts';

	// The page "System" (Tobi, 24.10.2026): what Lekto does by itself, for every user; acting
	// on it (training, trying jobs again) is for admins. The tab stands in the URL.
	const tab = $derived(systemTab(page.url.searchParams));
	const LABELS: Record<SystemTab, () => string> = {
		classifier: m.system_tab_classifier,
		jobs: m.system_tab_jobs
	};
</script>

<svelte:head><title>{LABELS[tab]()} · {m.nav_system()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-4 sm:gap-6">
	<h1 class="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">{m.nav_system()}</h1>
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
		{:else}
			<ClassifierTab />
		{/if}
	{/key}
</div>
