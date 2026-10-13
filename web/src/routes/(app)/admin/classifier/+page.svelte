<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import type { components } from '#lib/api/schema.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';

	// The classifier: what the latest model learned, how far the next training is, and a
	// training on request (it also trains on its own after enough confirmations).
	type Status = components['schemas']['ClassifierStatusOut'];

	let status = $state<Status | null>(null);
	let unavailable = $state(false);
	let problem = $state<string | null>(null);
	let busy = $state(false);

	async function load() {
		try {
			status = await unwrap(api.GET('/api/v1/classifier'));
			problem = null;
		} catch (failure) {
			if (failure instanceof ApiError && failure.status === 503) unavailable = true;
			else problem = describeError(failure);
		}
	}
	onMount(() => {
		if (session.isAdmin) void load();
	});

	async function train() {
		if (busy) return;
		busy = true;
		try {
			await unwrap(api.POST('/api/v1/classifier/train'));
			toast.success(m.classifier_train_queued());
		} catch (failure) {
			toast.error(describeError(failure));
		} finally {
			busy = false;
		}
	}

	const percent = (value: number | null) =>
		value === null ? '–' : formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
</script>

<svelte:head><title>{m.nav_classifier()} · p:api:q</title></svelte:head>

<div class="flex max-w-3xl flex-col gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_classifier()}</h1>
		{#if session.isAdmin && status}
			<Button onclick={train} disabled={busy}>{m.classifier_train()}</Button>
		{/if}
	</div>

	{#if !session.isAdmin}
		<p class="text-muted-foreground">{m.admin_only()}</p>
	{:else if unavailable}
		<p class="text-muted-foreground">{m.classifier_not_configured()}</p>
	{:else if problem}
		<div class="flex flex-col items-start gap-3" role="alert">
			<p class="text-destructive">{problem}</p>
			<Button variant="outline" onclick={load}>{m.retry()}</Button>
		</div>
	{:else if !status}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<p class="text-muted-foreground">{m.classifier_intro()}</p>
		<section class="flex flex-col gap-2 rounded-2xl border bg-card px-5 py-4">
			{#if status.model}
				{@const model = status.model}
				<h2 class="font-medium">
					{m.classifier_model({
						number: model.number,
						date: formatDate(model.trained_at, { dateStyle: 'medium', timeStyle: 'short' })
					})}
				</h2>
				<p>{m.classifier_examples({ count: formatNumber(model.examples) })}</p>
				<p>
					{m.classifier_classes({
						contacts: formatNumber(model.classes.contact),
						types: formatNumber(model.classes.document_type),
						tags: formatNumber(model.classes.tags)
					})}
				</p>
				<p>{m.classifier_identifiers({ count: formatNumber(model.learned_identifiers) })}</p>
				<p class="text-sm text-muted-foreground">
					{#if model.accuracy}
						{m.classifier_accuracy({
							tested: formatNumber(model.accuracy.tested),
							contact: percent(model.accuracy.contact),
							type: percent(model.accuracy.document_type)
						})}
					{:else}
						{m.classifier_accuracy_none()}
					{/if}
				</p>
				{#if model.method}
					<p class="font-mono text-xs text-muted-foreground">{model.method}</p>
				{/if}
			{:else}
				<h2 class="font-medium">{m.classifier_no_model()}</h2>
			{/if}
		</section>
		<p>
			{#if status.model}
				{m.classifier_next({
					since: formatNumber(status.since),
					needed: formatNumber(status.retrain_after)
				})}
			{:else}
				{m.classifier_first({
					confirmed: formatNumber(status.confirmed),
					needed: formatNumber(status.min_examples)
				})}
			{/if}
		</p>
	{/if}
</div>
