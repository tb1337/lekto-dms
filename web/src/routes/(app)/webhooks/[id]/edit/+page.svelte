<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import WebhookForm from '#lib/components/WebhookForm.svelte';
	import { describeError } from '#lib/errors.ts';
	import { m } from '#lib/paraglide/messages.js';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';

	type Webhook = components['schemas']['WebhookOut'];

	const id = $derived(page.params.id ?? '');
	let webhook = $state<Webhook | null>(null);
	let problem = $state<string | null>(null);

	// Bumped by "Try again" to load anew.
	let attempt = $state(0);

	$effect(() => {
		const wanted = id;
		void attempt;
		webhook = null;
		problem = null;
		unwrap(api.GET('/api/v1/webhooks/{id}', { params: { path: { id: wanted } } })).then(
			(found) => {
				if (wanted === id) webhook = found;
			},
			(error) => {
				if (wanted === id) problem = describeError(error);
			}
		);
	});
</script>

<svelte:head>
	<title
		>{webhook ? m.webhook_edit_named({ name: webhook.name }) : m.webhook_edit_generic()} · {m.app_name()}</title
	>
</svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader
		title={webhook ? m.webhook_edit_named({ name: webhook.name }) : m.webhook_edit_generic()}
		back={{ href: `${BASE}/webhooks/${id}`, label: webhook?.name ?? m.nav_webhooks() }}
	/>

	{#if problem}
		<LoadProblem {problem} onretry={() => attempt++} />
	{:else if !webhook}
		<p class="text-muted-foreground" role="status">{m.loading()}</p>
	{:else}
		{#key webhook.id}
			<WebhookForm
				{webhook}
				cancelHref="{BASE}/webhooks/{webhook.id}"
				ondone={(saved) => goto(`${BASE}/webhooks/${saved}`)}
			/>
		{/key}
	{/if}
</div>
