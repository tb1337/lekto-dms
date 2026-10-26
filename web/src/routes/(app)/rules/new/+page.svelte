<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { BASE } from '#lib/base.ts';
	import RuleBuilder from '#lib/components/rules/RuleBuilder.svelte';
	import { describeError } from '#lib/errors.ts';
	import { loadRuleLookup, spaceOptions, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { RuleForm } from '#lib/rules/form.svelte.ts';
	import { newModel, toApi } from '#lib/rules/model.ts';
	import { rulePlaces } from '#lib/rules/places.ts';
	import { createSwitchedOff } from '#lib/rules/save.ts';
	import { session } from '#lib/session.svelte.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Loading from '#lib/components/Loading.svelte';

	const model = $state(newModel());
	// Empty: the caller's personal space, once the spaces are known.
	let chosen = $state('');
	let lookup = $state<Lookup | null>(null);
	let problem = $state<string | null>(null);
	const form = new RuleForm();

	// A rule belongs to a space the caller edits; admins also make global ones.
	const places = $derived(
		rulePlaces(lookup?.spaces ?? [], lookup?.users ?? [], session.user?.id, session.isAdmin)
	);
	const personal = $derived(
		lookup?.spaces.find((space) => space.personal_of === session.user?.id)?.id ?? ''
	);
	const place = $derived(chosen || personal);
	const targets = $derived(spaceOptions(lookup?.spaces ?? [], lookup?.users ?? [], session.user));

	function loadLookup() {
		problem = null;
		loadRuleLookup().then(
			(value) => (lookup = value),
			(error) => (problem = describeError(error))
		);
	}

	onMount(loadLookup);

	async function save() {
		if (!lookup || !form.check(model, lookup.fields)) return;
		const rule = await form.save(model, () => createSwitchedOff(place, toApi(model)));
		if (rule) await goto(`${BASE}/rules/${rule.id}/apply?saved=1`);
	}
</script>

<svelte:head><title>{m.rule_new_title()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader title={m.rule_new_title()} back={{ href: `${BASE}/rules`, label: m.nav_rules() }} />

	{#if problem}
		<LoadProblem {problem} onretry={loadLookup} />
	{:else if !lookup}
		<Loading />
	{:else}
		<RuleBuilder
			{model}
			{place}
			{places}
			onplace={(next) => (chosen = next)}
			{lookup}
			{targets}
			errors={form.errors}
			general={form.general}
			busy={form.busy}
			cancelHref="{BASE}/rules"
			onsubmit={save}
		/>
	{/if}
</div>
