<script lang="ts">
	import { goto } from '$app/navigation';
	import { BASE } from '#lib/base.ts';
	import WebhookForm from '#lib/components/WebhookForm.svelte';
	import { m } from '#lib/paraglide/messages.js';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
</script>

<svelte:head><title>{m.webhook_new()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader
		title={m.webhook_new()}
		back={{ href: `${BASE}/webhooks`, label: m.nav_webhooks() }}
	/>
	<WebhookForm cancelHref="{BASE}/webhooks" ondone={(id) => goto(`${BASE}/webhooks/${id}`)} />
</div>
