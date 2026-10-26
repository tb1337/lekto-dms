<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { BASE } from '#lib/base.ts';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import EditButton from '#lib/components/EditButton.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { userName, type UserName } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';

	type Webhook = components['schemas']['WebhookOut'];

	let hooks = $state<Webhook[] | null>(null);
	let users = $state<UserName[]>([]);
	let problem = $state<string | null>(null);
	const ownerName = (id: string) => userName(users, id);

	async function load() {
		try {
			[hooks, users] = await Promise.all([
				unwrap(api.GET('/api/v1/webhooks')),
				unwrap(api.GET('/api/v1/users'))
			]);
			problem = null;
		} catch (error) {
			problem = describeError(error);
		}
	}
	onMount(() => void load());
</script>

<svelte:head><title>{m.nav_webhooks()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<PageHeader title={m.nav_webhooks()}>
		{#snippet actions()}
			<a href="{BASE}/webhooks/new" class={cn(buttonVariants())}>
				<Plus aria-hidden="true" />
				{m.webhook_new()}
			</a>
		{/snippet}
	</PageHeader>

	{#if problem}
		<LoadProblem {problem} onretry={load} />
	{:else if !hooks}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else if hooks.length === 0}
		<EmptyNote>{m.webhook_none()}</EmptyNote>
	{:else}
		<ul class="flex flex-col gap-2">
			{#each hooks as hook (hook.id)}
				<Card.Root as="li" size="row" class="flex flex-wrap items-center gap-3">
					<div class="flex min-w-0 flex-1 flex-col gap-1">
						<span class="flex flex-wrap items-center gap-2">
							<a href="{BASE}/webhooks/{hook.id}" class="truncate font-medium hover:underline"
								>{hook.name}</a
							>
							<Badge variant={hook.active ? 'green' : 'muted'}>
								{hook.active ? m.webhook_on() : m.webhook_off()}
							</Badge>
							{#if !hook.signed}
								<Badge variant="yellow">{m.webhook_unsigned()}</Badge>
							{/if}
							{#if hook.model_call}
								<Badge variant="note">
									{hook.model_call.kind === 'propose'
										? m.webhook_model_call_propose()
										: m.webhook_model_call_extract()}
								</Badge>
							{/if}
							{#if session.isAdmin && hook.owner_id !== session.user?.id}
								<Badge variant="outline">{ownerName(hook.owner_id)}</Badge>
							{/if}
						</span>
						<span class="truncate font-mono text-sm text-muted-foreground">{hook.url}</span>
						{#if hook.disabled_reason === 'failing'}
							<span class="text-sm text-destructive"
								>{m.webhook_failing({ count: hook.failed_streak })}</span
							>
						{/if}
					</div>
					<EditButton
						label={m.webhook_edit_named({ name: hook.name })}
						href="{BASE}/webhooks/{hook.id}/edit"
					/>
				</Card.Root>
			{/each}
		</ul>
	{/if}
</div>
