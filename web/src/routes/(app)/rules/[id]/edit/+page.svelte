<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import RuleBuilder from '#lib/components/rules/RuleBuilder.svelte';
	import { spaceOptions } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { problemText } from '#lib/rules/describe.ts';
	import { saveErrors } from '#lib/rules/errors.ts';
	import { fromApi, toApi, validate, type RuleModel } from '#lib/rules/model.ts';
	import { RuleLoader } from '#lib/rules/page.svelte.ts';
	import { placeOf, rulePlaces } from '#lib/rules/places.ts';
	import { changeSwitchedOff } from '#lib/rules/save.ts';
	import { session } from '#lib/session.svelte.ts';

	type Rule = components['schemas']['RuleOut'];

	const id = $derived(page.params.id ?? '');
	let rule = $state<Rule | null>(null);
	let model = $state<RuleModel | null>(null);
	const loader = new RuleLoader();
	const lookup = $derived(loader.lookup);
	const problem = $derived(loader.problem);
	let errors = $state<Record<string, string>>({});
	let general = $state<string | null>(null);
	let busy = $state(false);
	// Where the rule moves to (empty: where it is); its space changes with its content.
	let chosen = $state('');
	const current = $derived(rule ? placeOf(rule) : '');
	const place = $derived(chosen || current);
	const places = $derived(
		rulePlaces(
			lookup?.spaces ?? [],
			lookup?.users ?? [],
			session.user?.id,
			session.isAdmin,
			current
		)
	);

	// The rule files where whoever saves it may file (the API checks it for the caller).
	const targets = $derived(spaceOptions(lookup?.spaces ?? [], lookup?.users ?? [], session.user));

	$effect(() => {
		const wanted = id;
		untrack(() =>
			loader.load(
				() => unwrap(api.GET('/api/v1/rules/{id}', { params: { path: { id: wanted } } })),
				(found) => {
					rule = found;
					model = fromApi(found);
				}
			)
		);
	});

	async function save() {
		if (!rule || !model || !lookup) return;
		const problems = validate(model, lookup.fields);
		errors = Object.fromEntries(
			Object.entries(problems).map(([key, entry]) => [key, problemText(entry)])
		);
		general = Object.keys(errors).length > 0 ? m.rule_form_invalid() : null;
		if (general) return;
		const definition = toApi(model);
		const before = toApi(fromApi(rule));
		const moved = place !== current;
		if (!moved && JSON.stringify(definition) === JSON.stringify(before)) {
			await goto(`${BASE}/rules/${rule.id}`);
			return;
		}
		busy = true;
		try {
			const saved = await changeSwitchedOff(rule, definition, moved ? place : undefined);
			toast.success(m.rule_saved());
			await goto(`${BASE}/rules/${saved.id}/apply?saved=1`);
		} catch (error) {
			({ byKey: errors, general } = saveErrors(error, model));
			if (!general && Object.keys(errors).length > 0) general = m.rule_form_invalid();
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head
	><title>{m.rule_edit_title({ name: rule?.name ?? '' })} · {m.app_name()}</title></svelte:head
>

<div class="flex flex-col gap-6">
	<a
		href="{BASE}/rules/{id}"
		class="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
	>
		<ArrowLeft class="size-4" aria-hidden="true" />
		{rule?.name ?? m.nav_rules()}
	</a>
	<h1 class="text-[1.75rem] font-semibold tracking-tight">
		{m.rule_edit_title({ name: rule?.name ?? '' })}
	</h1>

	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !rule || !model || !lookup}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<RuleBuilder
			{model}
			{place}
			{places}
			onplace={(next) => (chosen = next)}
			placeHint={m.rule_scope_move_hint()}
			{lookup}
			{targets}
			{errors}
			{general}
			{busy}
			cancelHref="{BASE}/rules/{rule.id}"
			onsubmit={save}
		/>
	{/if}
</div>
