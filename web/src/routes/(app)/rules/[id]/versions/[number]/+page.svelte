<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import RuleView from '#lib/components/rules/RuleView.svelte';
	import { formatDate } from '#lib/i18n.ts';
	import { userName } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { RuleLoader } from '#lib/rules/page.svelte.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';

	// One saved version of a rule, to read (decision E4: no restoring).
	const id = $derived(page.params.id ?? '');
	const number = $derived(Number(page.params.number ?? '0'));
	let version = $state<components['schemas']['RuleVersionOut'] | null>(null);
	const loader = new RuleLoader();
	const lookup = $derived(loader.lookup);
	const problem = $derived(loader.problem);

	$effect(() => {
		const [wantedId, wantedNumber] = [id, number];
		version = null;
		untrack(() =>
			loader.load(
				() =>
					unwrap(
						api.GET('/api/v1/rules/{id}/versions/{number}', {
							params: { path: { id: wantedId, number: wantedNumber } }
						})
					),
				(found) => (version = found)
			)
		);
	});

	const author = $derived(userName(lookup?.users ?? [], version?.created_by));
</script>

<svelte:head>
	<title>{m.rule_version_n({ number })} · {m.app_name()}</title>
</svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader
		title={version
			? m.rule_version_title({ name: version.name, number: version.version })
			: m.rule_version_n({ number })}
		back={{ href: `${BASE}/rules/${id}`, label: version?.name ?? m.nav_rules() }}
	>
		{#snippet below()}
			{#if version}
				<span class="text-sm text-muted-foreground">
					{m.rule_version_meta({
						date: formatDate(version.created_at, { dateStyle: 'medium', timeStyle: 'short' }),
						user: author
					})} · {m.rule_priority_short({ priority: version.priority })}
				</span>
			{/if}
		{/snippet}
	</PageHeader>
	{#if problem}
		<LoadProblem {problem} onretry={() => loader.retry()} />
	{:else if !version}
		<p class="text-muted-foreground" role="status">{m.loading()}</p>
	{:else}
		<p class="text-sm text-muted-foreground">{m.rule_version_hint()}</p>
		<Card.Root as="section">
			<RuleView definition={version} {lookup} />
		</Card.Root>
	{/if}
</div>
