<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import Play from '@lucide/svelte/icons/play';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import RuleView from '#lib/components/rules/RuleView.svelte';
	import TitlePatternBadge from '#lib/components/rules/TitlePatternBadge.svelte';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import { reportError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { userName } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { reasonsText } from '#lib/reasons.ts';
	import { canApplyRule, canChangeRule } from '#lib/permissions.ts';
	import { RuleLoader } from '#lib/rules/page.svelte.ts';
	import { moves, placeLabel, placeOf } from '#lib/rules/places.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import { onChange } from '#lib/watch.svelte.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import Loading from '#lib/components/Loading.svelte';

	type Rule = components['schemas']['RuleOut'];
	type Version = components['schemas']['RuleVersionOut'];

	const id = $derived(page.params.id ?? '');
	let rule = $state<Rule | null>(null);
	let versions = $state<Version[]>([]);
	const loader = new RuleLoader();
	const lookup = $derived(loader.lookup);
	const problem = $derived(loader.problem);
	let removing = $state(false);
	let busy = $state(false);

	const spaces = $derived(lookup?.spaces ?? []);
	const users = $derived(lookup?.users ?? []);
	const placeName = $derived(
		rule ? placeLabel(placeOf(rule), spaces, users, session.user?.id, m.rule_global) : ''
	);
	const moved = $derived(moves(versions));
	const placed = (place: string) => placeLabel(place, spaces, users, session.user?.id);

	/** The rule and its versions; `fresh` loads the names they show anew as well. */
	function load(fresh = false) {
		const wanted = id;
		if (rule?.id !== wanted) rule = null;
		return loader.load(
			() =>
				Promise.all([
					unwrap(api.GET('/api/v1/rules/{id}', { params: { path: { id: wanted } } })),
					unwrap(api.GET('/api/v1/rules/{id}/versions', { params: { path: { id: wanted } } }))
				]),
			([found, history]) => {
				rule = found;
				versions = [...history].reverse();
			},
			{ fresh }
		);
	}

	$effect(() => {
		void id;
		untrack(() => void load());
	});

	// Again after a master data dialog saved: a title pattern's rule follows its type, and the
	// types, tags and contacts the rule names may have been renamed.
	onChange(
		() => masterDataDialogs.changed,
		() => void load(true)
	);

	async function switchRule(enabled: boolean) {
		if (!rule) return;
		busy = true;
		try {
			rule = await unwrap(
				api.PATCH('/api/v1/rules/{id}', { params: { path: { id: rule.id } }, body: { enabled } })
			);
			toast.success(enabled ? m.rule_switched_on() : m.rule_switched_off());
		} catch (error) {
			reportError(error);
		} finally {
			busy = false;
		}
	}

	async function remove() {
		await unwrap(api.DELETE('/api/v1/rules/{id}', { params: { path: { id } } }));
		toast.success(m.rule_deleted());
		await goto(`${BASE}/rules`);
	}
</script>

<svelte:head><title>{rule?.name ?? m.nav_rules()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader
		title={rule?.name ?? m.rule_generic()}
		back={{ href: `${BASE}/rules`, label: m.nav_rules() }}
	>
		{#snippet actions()}
			{#if rule && canChangeRule(rule, session.user, spaces)}
				<Switch
					bind:checked={() => rule?.enabled ?? false, switchRule}
					disabled={busy}
					aria-label={rule.enabled
						? m.rule_switch_off({ name: rule.name })
						: m.rule_switch_on({ name: rule.name })}
				/>
				<a href="{BASE}/rules/{rule.id}/edit" class={cn(buttonVariants({ variant: 'outline' }))}>
					<Pencil aria-hidden="true" />
					{m.rule_edit()}
				</a>
			{/if}
			{#if rule && canApplyRule(rule, session.user, spaces)}
				<a href="{BASE}/rules/{rule.id}/apply" class={cn(buttonVariants({ variant: 'outline' }))}>
					<Play aria-hidden="true" />
					{m.rule_apply()}
				</a>
			{/if}
			{#if rule && canChangeRule(rule, session.user, spaces)}
				<IconButton label={m.rule_delete({ name: rule.name })} onclick={() => (removing = true)}>
					<Trash2 aria-hidden="true" />
				</IconButton>
			{/if}
		{/snippet}
		{#snippet below()}
			{#if rule}
				<span class="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<Badge variant="note">{placeName}</Badge>
					{#if rule.managed_by_document_type_id}
						<TitlePatternBadge
							documentTypeId={rule.managed_by_document_type_id}
							name={rule.name}
							ruleId={rule.id}
						/>
					{/if}
					{#if !canChangeRule(rule, session.user, spaces)}
						<!-- The switch says it where the reader may change it. -->
						<Badge variant={rule.enabled ? 'green' : 'muted'}>
							{rule.enabled ? m.rule_on() : m.rule_off()}
						</Badge>
					{/if}
					{m.rule_priority_short({ priority: rule.priority })}
				</span>
				{#if rule.disabled_reason}
					<span class="text-sm text-destructive">
						{m.rule_disabled_reason({
							reason: reasonsText(rule.disabled_reasons, rule.disabled_reason) ?? ''
						})}
					</span>
				{/if}
				{#if rule.managed_by_document_type_id}
					<p class="max-w-prose text-sm text-muted-foreground">
						{m.rule_title_pattern_hint({ type: rule.name })}
					</p>
				{/if}
			{/if}
		{/snippet}
	</PageHeader>

	{#if problem}
		<LoadProblem {problem} onretry={() => loader.retry()} />
	{:else if !rule}
		<Loading />
	{:else}
		<Card.Root as="section">
			<RuleView definition={rule} {lookup} />
		</Card.Root>

		<section class="flex flex-col gap-3" aria-labelledby="rule-versions">
			<SectionTitle id="rule-versions">{m.rule_versions()}</SectionTitle>
			<ul class="flex flex-col gap-1">
				{#each versions as version (version.version)}
					<li class="flex flex-wrap items-center gap-2 text-sm">
						<a
							href="{BASE}/rules/{rule.id}/versions/{version.version}"
							class="font-medium hover:underline"
						>
							{m.rule_version_n({ number: version.version })}
						</a>
						{#if version.version === rule.version}
							<Badge variant="primary">{m.rule_version_current()}</Badge>
						{/if}
						<span class="text-muted-foreground">
							{m.rule_version_meta({
								date: formatDate(version.created_at, { dateStyle: 'medium', timeStyle: 'short' }),
								user: userName(users, version.created_by)
							})}
						</span>
						{#if moved.get(version.version)}
							{@const [from, to] = moved.get(version.version) ?? ['', '']}
							<span class="text-muted-foreground"
								>· {m.rule_version_moved({ from: placed(from), to: placed(to) })}</span
							>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</div>

<ConfirmDialog
	bind:open={removing}
	title={m.rule_delete({ name: rule?.name ?? '' })}
	description={m.rule_delete_confirm()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
