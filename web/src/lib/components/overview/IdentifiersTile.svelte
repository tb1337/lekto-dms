<script lang="ts">
	import IdCard from '@lucide/svelte/icons/id-card';
	import { onMount } from 'svelte';
	import { BASE } from '#lib/base.ts';
	import Figure from '#lib/components/overview/Figure.svelte';
	import Tile from '#lib/components/overview/Tile.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Skeleton } from '#lib/components/ui/skeleton/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { type OpenCounts, openCounts, openTotal } from '#lib/open-identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The open identifiers on the overview (admins): how many no person has confirmed, learned,
	// unknown and suggested, and the way to the tab of master data that decides them.
	let counts = $state<OpenCounts | null>(null);
	let problem = $state<string | null>(null);

	async function load() {
		try {
			counts = await openCounts();
			problem = null;
		} catch (error) {
			problem = describeError(error);
		}
	}

	onMount(() => {
		void load();
	});
</script>

<Tile
	title={m.master_identifiers()}
	icon={IdCard}
	href={`${BASE}/admin/master-data?tab=identifiers`}
	go={m.overview_identifiers_go()}
>
	{#if problem}
		<LoadProblem {problem} onretry={load} />
	{:else if !counts}
		<Skeleton class="h-9 w-24" />
	{:else}
		<Figure count={openTotal(counts)} label={m.overview_identifiers_unconfirmed()} />
		<ul class="flex flex-wrap gap-1.5">
			<li>
				<Badge variant="note"
					>{m.overview_identifiers_learned({ count: formatNumber(counts.learned) })}</Badge
				>
			</li>
			<li>
				<Badge variant="muted"
					>{m.overview_identifiers_unknown({ count: formatNumber(counts.unknown) })}</Badge
				>
			</li>
			{#if counts.suggested > 0}
				<li>
					<Badge variant="primary"
						>{m.overview_identifiers_suggested({ count: formatNumber(counts.suggested) })}</Badge
					>
				</li>
			{/if}
		</ul>
		<p class="text-meta text-muted-foreground">{m.overview_identifiers_hint()}</p>
	{/if}
</Tile>
