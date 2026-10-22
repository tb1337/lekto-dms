<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
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
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { loadLookup, spaceLabel, userLabel, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { canApplyRule, canChangeRule } from '#lib/permissions.ts';
	import { moves, placeLabel } from '#lib/rules/places.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	type Rule = components['schemas']['RuleOut'];
	type Version = components['schemas']['RuleVersionOut'];

	const id = $derived(page.params.id ?? '');
	let rule = $state<Rule | null>(null);
	let versions = $state<Version[]>([]);
	let lookup = $state<Lookup | null>(null);
	let problem = $state<string | null>(null);
	let removing = $state(false);
	let busy = $state(false);

	const userName = (user: string | null) => {
		const found = lookup?.users.find((entry) => entry.id === user);
		return found ? userLabel(found) : m.rule_unknown();
	};
	const placeName = $derived.by(() => {
		if (!rule || rule.scope === 'global') return m.rule_global();
		const space = lookup?.spaces.find((entry) => entry.id === rule?.space_id);
		return space ? spaceLabel(space, lookup?.users ?? [], session.user?.id) : m.rule_unknown();
	});
	const spaces = $derived(lookup?.spaces ?? []);
	const moved = $derived(moves(versions));
	const placed = (place: string) =>
		placeLabel(place, spaces, lookup?.users ?? [], session.user?.id);

	// Again after a master data dialog saved: a title pattern's rule follows its type.
	$effect(() => {
		const wanted = id;
		void masterDataDialogs.changed;
		if (untrack(() => rule)?.id !== wanted) rule = null;
		Promise.all([
			unwrap(api.GET('/api/v1/rules/{id}', { params: { path: { id: wanted } } })),
			unwrap(api.GET('/api/v1/rules/{id}/versions', { params: { path: { id: wanted } } })),
			untrack(() => lookup) ?? loadLookup()
		]).then(
			([found, history, loaded]) => {
				if (wanted !== id) return;
				[rule, versions, lookup, problem] = [found, [...history].reverse(), loaded, null];
			},
			(error) => {
				if (wanted === id) problem = describeError(error);
			}
		);
	});

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
	<a
		href="{BASE}/rules"
		class="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
	>
		<ArrowLeft class="size-4" aria-hidden="true" />
		{m.nav_rules()}
	</a>

	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !rule}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div class="flex min-w-0 flex-col gap-2">
				<h1 class="text-[1.75rem] font-semibold tracking-tight break-words">{rule.name}</h1>
				<span class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<Badge variant={rule.scope === 'global' ? 'secondary' : 'outline'}>
						{placeName}
					</Badge>
					{#if rule.managed_by_document_type_id}
						<TitlePatternBadge
							documentTypeId={rule.managed_by_document_type_id}
							name={rule.name}
							ruleId={rule.id}
						/>
					{/if}
					<Badge variant={rule.enabled ? 'secondary' : 'outline'}>
						{rule.enabled ? m.rule_on() : m.rule_off()}
					</Badge>
					{m.rule_priority_short({ priority: rule.priority })}
				</span>
				{#if rule.disabled_reason}
					<span class="text-sm text-destructive">
						{m.rule_disabled_reason({ reason: rule.disabled_reason })}
					</span>
				{/if}
				{#if rule.managed_by_document_type_id}
					<p class="max-w-prose text-sm text-muted-foreground">
						{m.rule_title_pattern_hint({ type: rule.name })}
					</p>
				{/if}
			</div>
			<div class="flex flex-wrap items-center gap-2">
				{#if canChangeRule(rule, session.user, spaces)}
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
				{#if canApplyRule(rule, session.user, spaces)}
					<a href="{BASE}/rules/{rule.id}/apply" class={cn(buttonVariants({ variant: 'outline' }))}>
						<Play aria-hidden="true" />
						{m.rule_apply()}
					</a>
				{/if}
				{#if canChangeRule(rule, session.user, spaces)}
					<Button
						variant="ghost"
						size="icon"
						aria-label={m.rule_delete({ name: rule.name })}
						onclick={() => (removing = true)}
					>
						<Trash2 aria-hidden="true" />
					</Button>
				{/if}
			</div>
		</div>

		<section class="rounded-2xl border bg-card p-5">
			<RuleView definition={rule} {lookup} />
		</section>

		<section class="flex flex-col gap-3" aria-labelledby="rule-versions">
			<h2 id="rule-versions" class="text-lg font-semibold">{m.rule_versions()}</h2>
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
							<Badge variant="secondary">{m.rule_version_current()}</Badge>
						{/if}
						<span class="text-muted-foreground">
							{m.rule_version_meta({
								date: formatDate(version.created_at, { dateStyle: 'medium', timeStyle: 'short' }),
								user: userName(version.created_by)
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
