<script lang="ts">
	import KeyRound from '@lucide/svelte/icons/key-round';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Send from '@lucide/svelte/icons/send';
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import SecretDialog from '#lib/components/SecretDialog.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { openBeam } from '#lib/beam.svelte.ts';
	import BeamTitle from '#lib/components/BeamTitle.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { rememberedPageSize } from '#lib/page-size.ts';
	import { Pager } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { canManageWebhook } from '#lib/permissions.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import { eventLabel, sendTest } from '#lib/webhooks.ts';
	import type { Tone } from '#lib/tones.ts';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import Loading from '#lib/components/Loading.svelte';

	type Webhook = components['schemas']['WebhookOut'];
	type Outcome = components['schemas']['DeliveryOutcome'];
	type Delivery = components['schemas']['DeliveryOut'];
	type Summary = components['schemas']['DeliverySummaryOut'];
	type View = 'all' | 'problems' | 'delivered';

	// The page of a webhook: what it is, with the way to its editor, and its deliveries as a
	// table with pages (Tobi, 27.10.2026, after a mock): all of them, the problems (another
	// attempt follows, given up, not sent) or the delivered ones, of one event if chosen, each
	// with its document as far as the viewer may read it.
	const id = $derived(page.params.id ?? '');
	let webhook = $state<Webhook | null>(null);
	let problem = $state<string | null>(null);
	let removing = $state(false);
	let renewing = $state(false);
	let secret = $state<string | null>(null);
	let busy = $state(false);

	const OUTCOMES: Record<View, Outcome[] | undefined> = {
		all: undefined,
		problems: ['retrying', 'gave_up', 'dropped'],
		delivered: ['delivered']
	};
	let view = $state<View>('all');
	let eventType = $state('');
	let summary = $state<Summary | null>(null);
	// The summary of the latest page asked for wins over one that comes late.
	let asked = 0;

	function counted(found: Summary, shown: View): number {
		const problems = found.retrying + found.gave_up + found.dropped;
		if (shown === 'problems') return problems;
		if (shown === 'delivered') return found.delivered;
		return problems + found.delivered;
	}

	const deliveries = new Pager<Delivery>(async (offset, limit) => {
		const ask = ++asked;
		const path = { id };
		const event_type = eventType || undefined;
		const [found, counts] = await Promise.all([
			unwrap(
				api.GET('/api/v1/webhooks/{id}/deliveries', {
					params: { path, query: { outcome: OUTCOMES[view], event_type, offset, limit } }
				})
			),
			unwrap(
				api.GET('/api/v1/webhooks/{id}/deliveries/summary', {
					params: { path, query: { event_type } }
				})
			)
		]);
		if (ask === asked) summary = counts;
		return { items: found.items, total: found.total };
	}, rememberedPageSize('deliveries'));

	function show(next: string) {
		view = next as View;
		void deliveries.go(1);
	}

	function chooseEvent(next: string) {
		eventType = next;
		void deliveries.go(1);
	}

	const views = $derived(
		(['all', 'problems', 'delivered'] as const).map((value) => ({
			value,
			label: VIEW_LABELS[value](),
			count: summary ? formatNumber(counted(summary, value)) : undefined
		}))
	);
	const eventOptions = $derived([
		{ value: '', label: m.webhook_events_all() },
		...[...new Set([...(summary?.event_types ?? []), ...(eventType ? [eventType] : [])])].map(
			(type) => ({ value: type, label: eventLabel(type) })
		)
	]);
	const keptSince = $derived(
		summary ? formatDate(summary.kept_since, { dateStyle: 'medium' }) : ''
	);
	const filtered = $derived(view !== 'all' || eventType !== '');
	const NUMBER = 'text-right tabular-nums';

	async function load(wanted: string) {
		problem = null;
		try {
			const hook = await unwrap(
				api.GET('/api/v1/webhooks/{id}', { params: { path: { id: wanted } } })
			);
			if (wanted === id) webhook = hook;
		} catch (error) {
			if (wanted === id) problem = describeError(error);
		}
	}

	async function remove() {
		await unwrap(api.DELETE('/api/v1/webhooks/{id}', { params: { path: { id } } }));
		toast.success(m.webhook_deleted());
		await goto(`${BASE}/webhooks`);
	}

	$effect(() => {
		const wanted = id;
		webhook = null;
		// Only the webhook starts the page over, not the choice it reads while it loads.
		untrack(() => {
			view = 'all';
			eventType = '';
			summary = null;
			void deliveries.reload();
		});
		void load(wanted);
	});

	async function test() {
		busy = true;
		try {
			await sendTest(id);
			await deliveries.go(1);
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

	const OUTCOME_TONE: Record<Outcome, Tone> = {
		delivered: 'green',
		retrying: 'yellow',
		gave_up: 'red',
		dropped: 'muted'
	};

	const VIEW_LABELS: Record<View, () => string> = {
		all: m.delivery_view_all,
		problems: m.delivery_view_problems,
		delivered: m.delivery_view_delivered
	};

	const outcomeLabel: Record<Outcome, () => string> = {
		delivered: m.delivery_delivered,
		retrying: m.delivery_retrying,
		gave_up: m.delivery_gave_up,
		dropped: m.delivery_dropped
	};
</script>

<svelte:head><title>{webhook?.name ?? m.nav_webhooks()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader
		title={webhook?.name ?? m.webhook_generic()}
		back={{ href: `${BASE}/webhooks`, label: m.nav_webhooks() }}
	>
		{#snippet actions()}
			{#if webhook && canManageWebhook(webhook, session.user)}
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
					<IconButton
						label={m.webhook_renew({ name: webhook.name })}
						onclick={() => (renewing = true)}
					>
						<KeyRound aria-hidden="true" />
					</IconButton>
				{/if}
				<IconButton
					label={m.webhook_delete({ name: webhook.name })}
					onclick={() => (removing = true)}
				>
					<Trash2 aria-hidden="true" />
				</IconButton>
			{/if}
		{/snippet}
		{#snippet below()}
			{#if webhook}
				<span class="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
					<Badge variant={webhook.active ? 'green' : 'muted'}>
						{webhook.active ? m.webhook_on() : m.webhook_off()}
					</Badge>
					{#if !webhook.signed}
						<Badge variant="yellow">{m.webhook_unsigned()}</Badge>
					{/if}
					{#if webhook.model_call}
						<Badge variant="note">
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
			{/if}
		{/snippet}
	</PageHeader>

	{#if problem}
		<LoadProblem {problem} onretry={() => void load(id)} />
	{:else if !webhook}
		<Loading />
	{/if}

	{#if summary && summary.event_types.length > 0}
		<div class="flex flex-wrap items-center justify-between gap-3">
			<Segmented label={m.webhook_log()} value={view} onchange={show} options={views} />
			<Select
				aria-label={m.delivery_event()}
				class="w-auto min-w-56"
				value={eventType}
				onchange={chooseEvent}
				options={eventOptions}
			/>
		</div>
	{/if}

	<Card.Root as="section" size="lg" aria-labelledby="webhook-deliveries">
		<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
			<SectionTitle id="webhook-deliveries" size="card">{m.webhook_log()}</SectionTitle>
			{#if keptSince}
				<span class="text-meta text-muted-foreground">
					{m.delivery_kept_since({ date: keptSince })}
				</span>
			{/if}
		</div>
		{#if deliveries.error && !deliveries.loaded}
			<div class="mt-3">
				<LoadProblem
					problem={describeError(deliveries.error)}
					onretry={() => deliveries.reload()}
				/>
			</div>
		{:else if deliveries.empty}
			<p class="mt-3 text-muted-foreground">
				{filtered ? m.delivery_none_chosen() : m.delivery_none()}
			</p>
		{:else if deliveries.items.length}
			<div class="mt-3">
				<Table.Root class="min-w-[760px] text-meta">
					<Table.Header>
						<Table.Row class="text-xs text-muted-foreground">
							<Table.Head class="pl-0">{m.delivery_time()}</Table.Head>
							<Table.Head>{m.delivery_event()}</Table.Head>
							<Table.Head>{m.jobs_col_document()}</Table.Head>
							<Table.Head>{m.log_outcome()}</Table.Head>
							<Table.Head class={NUMBER}>{m.delivery_status()}</Table.Head>
							<Table.Head class={cn(NUMBER, 'pr-0')}>{m.log_duration()}</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each deliveries.items as delivery (delivery.id)}
							<Table.Row class={cn(delivery.error && 'border-b-0')}>
								<Table.Cell class="pl-0 text-muted-foreground tabular-nums">
									{formatDate(delivery.started_at, { dateStyle: 'short', timeStyle: 'medium' })}
								</Table.Cell>
								<Table.Cell>
									<span class="font-medium">{eventLabel(delivery.event_type)}</span>
									{#if delivery.attempt > 1}
										<span class="block text-xs text-muted-foreground">
											{m.delivery_attempt({ attempt: delivery.attempt })}
										</span>
									{/if}
								</Table.Cell>
								<Table.Cell class="max-w-[20rem] truncate">
									{#if delivery.document}
										{@const shown = delivery.document}
										<BeamTitle
											title={shown.title}
											class="max-w-full"
											onview={() =>
												openBeam(
													deliveries.items.flatMap((each) =>
														each.document ? [each.document.id] : []
													),
													shown.id,
													m.webhook_log()
												)}
										/>
									{:else if delivery.document_hidden}
										<span class="text-muted-foreground italic">{m.jobs_hidden_document()}</span>
									{:else}
										<span class="text-muted-foreground">–</span>
									{/if}
								</Table.Cell>
								<Table.Cell>
									<Badge variant={OUTCOME_TONE[delivery.outcome]}>
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
								<Table.Cell class={NUMBER}>{delivery.status_code ?? '–'}</Table.Cell>
								<Table.Cell class={cn(NUMBER, 'pr-0 text-muted-foreground')}>
									{m.delivery_duration({ ms: formatNumber(delivery.duration_ms) })}
								</Table.Cell>
							</Table.Row>
							{#if delivery.error}
								<Table.Row>
									<Table.Cell
										colspan={6}
										class="pt-0 pl-0 text-xs whitespace-normal text-lane-red-foreground"
									>
										{delivery.error}
									</Table.Cell>
								</Table.Row>
							{/if}
						{/each}
					</Table.Body>
				</Table.Root>
			</div>
			<div class="mt-4">
				<Pagination
					page={deliveries.page}
					total={deliveries.total}
					size={deliveries.size}
					table="deliveries"
					onchange={(next) => deliveries.go(next)}
					onsize={(next) => deliveries.resize(next)}
				/>
			</div>
		{:else}
			<Loading class="mt-3" />
		{/if}
	</Card.Root>
</div>

<ConfirmDialog
	bind:open={removing}
	title={m.webhook_delete({ name: webhook?.name ?? '' })}
	description={m.webhook_delete_confirm()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
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
