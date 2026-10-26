<script lang="ts">
	import KeyRound from '@lucide/svelte/icons/key-round';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Send from '@lucide/svelte/icons/send';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import BackLink from '#lib/components/BackLink.svelte';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import SecretDialog from '#lib/components/SecretDialog.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { PagedList } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { canManageWebhook } from '#lib/permissions.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import { sendTest } from '#lib/webhooks.ts';

	type Webhook = components['schemas']['WebhookOut'];
	type Outcome = components['schemas']['DeliveryOutcome'];

	// The page of a webhook: what it is, with the way to its editor, and its deliveries.
	const id = $derived(page.params.id ?? '');
	let webhook = $state<Webhook | null>(null);
	let renewing = $state(false);
	let secret = $state<string | null>(null);
	let busy = $state(false);

	const list = new PagedList<components['schemas']['DeliveryOut']>(async (before) => {
		const items = await unwrap(
			api.GET('/api/v1/webhooks/{id}/deliveries', {
				params: {
					path: { id },
					query: { before: (before as string | null) ?? undefined, limit: 50 }
				}
			})
		);
		// A full page may have more behind it; the next one starts after its last entry.
		return { items, next: items.length === 50 ? items[items.length - 1].id : null };
	});

	async function load(wanted: string) {
		try {
			const hook = await unwrap(
				api.GET('/api/v1/webhooks/{id}', { params: { path: { id: wanted } } })
			);
			if (wanted === id) webhook = hook;
		} catch (error) {
			if (wanted === id) reportError(error);
		}
	}

	$effect(() => {
		const wanted = id;
		webhook = null;
		void list.reload();
		void load(wanted);
	});

	async function test() {
		busy = true;
		try {
			await sendTest(id);
			await list.reload();
		} finally {
			busy = false;
		}
	}

	async function renew() {
		const renewed = await unwrap(
			api.POST('/api/v1/webhooks/{id}/secret', { params: { path: { id } } })
		);
		secret = renewed.secret;
		await load(id);
	}

	const outcomeLabel: Record<Outcome, () => string> = {
		delivered: m.delivery_delivered,
		retrying: m.delivery_retrying,
		gave_up: m.delivery_gave_up,
		dropped: m.delivery_dropped
	};
</script>

<svelte:head><title>{webhook?.name ?? m.nav_webhooks()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<BackLink href="{BASE}/webhooks" label={m.nav_webhooks()} />

	{#if webhook}
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div class="flex min-w-0 flex-col gap-2">
				<h1 class="text-[1.75rem] font-semibold tracking-tight break-words">{webhook.name}</h1>
				<span class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<Badge variant={webhook.active ? 'secondary' : 'outline'}>
						{webhook.active ? m.webhook_on() : m.webhook_off()}
					</Badge>
					{#if !webhook.signed}
						<Badge variant="outline">{m.webhook_unsigned()}</Badge>
					{/if}
					{#if webhook.model_call}
						<Badge variant="outline">
							{webhook.model_call.kind === 'propose'
								? m.webhook_model_call_propose()
								: m.webhook_model_call_extract()}
						</Badge>
					{/if}
				</span>
				<span class="font-mono text-sm break-all text-muted-foreground">{webhook.url}</span>
				{#if webhook.disabled_reason === 'failing'}
					<span class="text-sm text-destructive">
						{m.webhook_failing({ count: webhook.failed_streak })}
					</span>
				{/if}
			</div>
			{#if canManageWebhook(webhook, session.user)}
				<div class="flex flex-wrap items-center gap-2">
					<a
						href="{BASE}/webhooks/{webhook.id}/edit"
						class={cn(buttonVariants({ variant: 'outline' }))}
					>
						<Pencil aria-hidden="true" />
						{m.webhook_edit_do()}
					</a>
					<Button variant="outline" disabled={busy} onclick={test}>
						<Send aria-hidden="true" />
						{m.webhook_test()}
					</Button>
					{#if webhook.signed}
						<Button
							variant="ghost"
							size="icon"
							aria-label={m.webhook_renew({ name: webhook.name })}
							title={m.webhook_renew_do()}
							onclick={() => (renewing = true)}
						>
							<KeyRound aria-hidden="true" />
						</Button>
					{/if}
				</div>
			{/if}
		</div>
	{:else}
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.loading()}</h1>
	{/if}

	<section class="flex flex-col gap-3" aria-labelledby="webhook-deliveries">
		<h2 id="webhook-deliveries" class="text-lg font-semibold">{m.webhook_log()}</h2>
		{#if list.error}
			<LoadProblem problem={describeError(list.error)} onretry={() => list.reload()} />
		{:else if list.empty}
			<EmptyNote>{m.delivery_none()}</EmptyNote>
		{:else}
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>{m.delivery_time()}</Table.Head>
						<Table.Head>{m.delivery_event()}</Table.Head>
						<Table.Head>{m.log_outcome()}</Table.Head>
						<Table.Head>{m.delivery_status()}</Table.Head>
						<Table.Head>{m.log_duration()}</Table.Head>
						<Table.Head>{m.delivery_error()}</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each list.items as delivery (delivery.id)}
						<Table.Row>
							<Table.Cell>
								{formatDate(delivery.started_at, { dateStyle: 'short', timeStyle: 'medium' })}
							</Table.Cell>
							<Table.Cell>
								{delivery.event_type}
								<span class="block text-xs text-muted-foreground">
									{m.delivery_attempt({ attempt: delivery.attempt })}
								</span>
							</Table.Cell>
							<Table.Cell>
								<Badge variant={delivery.outcome === 'delivered' ? 'secondary' : 'outline'}>
									{outcomeLabel[delivery.outcome]()}
								</Badge>
								{#if delivery.next_attempt_at}
									<span class="block text-xs text-muted-foreground">
										{m.delivery_next({
											time: formatDate(delivery.next_attempt_at, {
												timeStyle: 'short',
												dateStyle: 'short'
											})
										})}
									</span>
								{/if}
							</Table.Cell>
							<Table.Cell>{delivery.status_code ?? '–'}</Table.Cell>
							<Table.Cell>{`${delivery.duration_ms} ms`}</Table.Cell>
							<Table.Cell class="max-w-xs whitespace-normal">{delivery.error ?? '–'}</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
			{#if list.hasMore}
				<div class="flex justify-center">
					<Button variant="outline" disabled={list.loading} onclick={() => list.more()}>
						{m.load_more()}
					</Button>
				</div>
			{/if}
		{/if}
	</section>
</div>

<ConfirmDialog
	bind:open={renewing}
	title={m.webhook_renew({ name: webhook?.name ?? '' })}
	description={m.webhook_renew_confirm()}
	confirmLabel={m.webhook_renew_do()}
	destructive={false}
	onconfirm={renew}
/>
<SecretDialog
	{secret}
	title={m.webhook_secret_title({ name: webhook?.name ?? '' })}
	description={m.webhook_secret_hint()}
	onclose={() => (secret = null)}
/>
