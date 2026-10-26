<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import BackLink from '#lib/components/BackLink.svelte';
	import WebhookForm from '#lib/components/WebhookForm.svelte';
	import { describeError } from '#lib/errors.ts';
	import { m } from '#lib/paraglide/messages.js';

	type Webhook = components['schemas']['WebhookOut'];

	const id = $derived(page.params.id ?? '');
	let webhook = $state<Webhook | null>(null);
	let problem = $state<string | null>(null);

	$effect(() => {
		const wanted = id;
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
	<title>{m.webhook_edit_named({ name: webhook?.name ?? '' })} · {m.app_name()}</title>
</svelte:head>

<div class="flex flex-col gap-6">
	<BackLink href="{BASE}/webhooks/{id}" label={webhook?.name ?? m.nav_webhooks()} />
	<h1 class="text-[1.75rem] font-semibold tracking-tight break-words">
		{m.webhook_edit_named({ name: webhook?.name ?? '' })}
	</h1>

	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !webhook}
		<p class="text-muted-foreground">{m.loading()}</p>
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
