<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import EditButton from '#lib/components/EditButton.svelte';
	import TitlePatternBadge from '#lib/components/rules/TitlePatternBadge.svelte';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import type { Space, UserName } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { reasonsText } from '#lib/reasons.ts';
	import { scope } from '#lib/scope.svelte.ts';
	import { canChangeRule } from '#lib/permissions.ts';
	import { TRIGGER_LABELS } from '#lib/rules/describe.ts';
	import { placeLabel, placeOf } from '#lib/rules/places.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';

	type Rule = components['schemas']['RuleOut'];

	let rules = $state<Rule[] | null>(null);
	let users = $state<UserName[]>([]);
	let spaces = $state<Space[]>([]);
	let problem = $state<string | null>(null);
	let removing = $state<Rule | null>(null);
	let busy = $state<string | null>(null);

	const placeName = (rule: Rule) =>
		placeLabel(placeOf(rule), spaces, users, session.user?.id, m.rule_global);

	let loads = 0;

	async function load() {
		const current = ++loads;
		try {
			const [found, names, known] = await Promise.all([
				unwrap(
					api.GET('/api/v1/rules', {
						params: { query: { include_disabled: true, all_users: scope.query } }
					})
				),
				users.length > 0 ? users : unwrap(api.GET('/api/v1/users')),
				unwrap(api.GET('/api/v1/spaces', { params: { query: { all_users: scope.query } } }))
			]);
			// An earlier answer arriving late (the toggle switched twice) is dropped.
			if (current !== loads) return;
			[rules, users, spaces, problem] = [found, names, known, null];
		} catch (error) {
			if (current === loads) problem = describeError(error);
		}
	}

	// Again after a master data dialog saved (a title pattern's rule follows its type), and
	// when the scope setting changes.
	$effect(() => {
		void masterDataDialogs.changed;
		void scope.allUsers;
		untrack(() => void load());
	});

	async function switchRule(rule: Rule, enabled: boolean) {
		busy = rule.id;
		try {
			const changed = await unwrap(
				api.PATCH('/api/v1/rules/{id}', { params: { path: { id: rule.id } }, body: { enabled } })
			);
			rules = (rules ?? []).map((entry) => (entry.id === changed.id ? changed : entry));
			toast.success(enabled ? m.rule_switched_on() : m.rule_switched_off());
		} catch (error) {
			reportError(error);
		} finally {
			busy = null;
		}
	}

	async function remove() {
		if (!removing) return;
		await unwrap(api.DELETE('/api/v1/rules/{id}', { params: { path: { id: removing.id } } }));
		toast.success(m.rule_deleted());
		await load();
	}
</script>

<svelte:head><title>{m.nav_rules()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_rules()}</h1>
		<a href="{BASE}/rules/new" class={cn(buttonVariants())}>
			<Plus aria-hidden="true" />
			{m.rules_new()}
		</a>
	</div>

	{#if problem}
		<div class="flex flex-col items-start gap-3" role="alert">
			<p class="text-destructive">{problem}</p>
			<Button variant="outline" onclick={load}>{m.retry()}</Button>
		</div>
	{:else if !rules}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else if rules.length === 0}
		<p
			class="rounded-2xl border border-dashed bg-card px-6 py-16 text-center text-muted-foreground"
		>
			{m.rules_none()}
		</p>
	{:else}
		<ul class="flex flex-col gap-2">
			{#each rules as rule (rule.id)}
				<li class="flex flex-wrap items-center gap-3 rounded-2xl border bg-card p-4">
					<div class="flex min-w-0 flex-1 flex-col gap-1">
						<span class="flex flex-wrap items-center gap-2">
							<a
								href="{BASE}/rules/{rule.id}"
								class="truncate font-medium hover:underline"
								aria-label={m.rule_open({ name: rule.name })}>{rule.name}</a
							>
							<Badge variant={rule.scope === 'global' ? 'secondary' : 'outline'}>
								{placeName(rule)}
							</Badge>
							{#if rule.managed_by_document_type_id}
								<TitlePatternBadge
									documentTypeId={rule.managed_by_document_type_id}
									name={rule.name}
									ruleId={rule.id}
								/>
							{/if}
							{#if !rule.enabled}<Badge variant="outline">{m.rule_off()}</Badge>{/if}
						</span>
						<span class="text-sm text-muted-foreground">
							{m.rule_priority_short({ priority: rule.priority })} ·
							{rule.triggers.map((trigger) => TRIGGER_LABELS[trigger]()).join(' · ')}
						</span>
						{#if rule.disabled_reason}
							<span class="text-sm text-destructive">
								{m.rule_disabled_reason({
									reason: reasonsText(rule.disabled_reasons, rule.disabled_reason) ?? ''
								})}
							</span>
						{/if}
					</div>
					{#if canChangeRule(rule, session.user, spaces)}
						<div class="flex items-center gap-2">
							<Switch
								bind:checked={() => rule.enabled, (enabled) => switchRule(rule, enabled)}
								disabled={busy === rule.id}
								aria-label={rule.enabled
									? m.rule_switch_off({ name: rule.name })
									: m.rule_switch_on({ name: rule.name })}
							/>
							<Button
								variant="ghost"
								size="icon"
								aria-label={m.rule_delete({ name: rule.name })}
								onclick={() => (removing = rule)}
							>
								<Trash2 aria-hidden="true" />
							</Button>
						</div>
						<EditButton
							label={m.rule_edit_title({ name: rule.name })}
							href="{BASE}/rules/{rule.id}/edit"
						/>
					{:else}
						<Badge variant={rule.enabled ? 'secondary' : 'outline'}>
							{rule.enabled ? m.rule_on() : m.rule_off()}
						</Badge>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<ConfirmDialog
	bind:open={() => removing !== null, (open) => !open && (removing = null)}
	title={m.rule_delete({ name: removing?.name ?? '' })}
	description={m.rule_delete_confirm()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
