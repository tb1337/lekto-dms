<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { BASE } from '#lib/base.ts';
	import RuleBuilder from '#lib/components/rules/RuleBuilder.svelte';
	import { describeError } from '#lib/errors.ts';
	import { loadLookup, spaceOptions, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { problemText } from '#lib/rules/describe.ts';
	import { saveErrors } from '#lib/rules/errors.ts';
	import { newModel, toApi, validate } from '#lib/rules/model.ts';
	import { rulePlaces } from '#lib/rules/places.ts';
	import { createSwitchedOff } from '#lib/rules/save.ts';
	import { session } from '#lib/session.svelte.ts';

	const model = $state(newModel());
	// Empty: the caller's personal space, once the spaces are known.
	let chosen = $state('');
	let lookup = $state<Lookup | null>(null);
	let problem = $state<string | null>(null);
	let errors = $state<Record<string, string>>({});
	let general = $state<string | null>(null);
	let busy = $state(false);

	// A rule belongs to a space the caller edits; admins also make global ones.
	const places = $derived(
		rulePlaces(lookup?.spaces ?? [], lookup?.users ?? [], session.user?.id, session.isAdmin)
	);
	const personal = $derived(
		lookup?.spaces.find((space) => space.personal_of === session.user?.id)?.id ?? ''
	);
	const place = $derived(chosen || personal);
	const targets = $derived(spaceOptions(lookup?.spaces ?? [], lookup?.users ?? [], session.user));

	onMount(() => {
		loadLookup().then(
			(value) => (lookup = value),
			(error) => (problem = describeError(error))
		);
	});

	async function save() {
		if (!lookup) return;
		const problems = validate(model, lookup.fields);
		errors = Object.fromEntries(
			Object.entries(problems).map(([key, entry]) => [key, problemText(entry)])
		);
		general = Object.keys(errors).length > 0 ? m.rule_form_invalid() : null;
		if (general) return;
		busy = true;
		try {
			const rule = await createSwitchedOff(place, toApi(model));
			toast.success(m.rule_saved());
			await goto(`${BASE}/rules/${rule.id}/apply?saved=1`);
		} catch (error) {
			({ byKey: errors, general } = saveErrors(error, model));
			if (!general && Object.keys(errors).length > 0) general = m.rule_form_invalid();
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>{m.rule_new_title()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<a
		href="{BASE}/rules"
		class="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
	>
		<ArrowLeft class="size-4" aria-hidden="true" />
		{m.nav_rules()}
	</a>
	<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.rule_new_title()}</h1>

	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !lookup}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<RuleBuilder
			{model}
			{place}
			{places}
			onplace={(next) => (chosen = next)}
			{lookup}
			{targets}
			{errors}
			{general}
			{busy}
			cancelHref="{BASE}/rules"
			onsubmit={save}
		/>
	{/if}
</div>
