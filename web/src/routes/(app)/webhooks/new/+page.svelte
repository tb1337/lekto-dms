<script lang="ts">
	import { goto } from '$app/navigation';
	import { BASE } from '#lib/base.ts';
	import BackLink from '#lib/components/BackLink.svelte';
	import WebhookForm from '#lib/components/WebhookForm.svelte';
	import { m } from '#lib/paraglide/messages.js';
</script>

<svelte:head><title>{m.webhook_new()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<BackLink href="{BASE}/webhooks" label={m.nav_webhooks()} />
	<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.webhook_new()}</h1>
	<WebhookForm cancelHref="{BASE}/webhooks" ondone={(id) => goto(`${BASE}/webhooks/${id}`)} />
</div>
