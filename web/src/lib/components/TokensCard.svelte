<script lang="ts">
	import { onMount } from 'svelte';
	import Trash from '@lucide/svelte/icons/trash-2';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import Select from '#lib/components/Select.svelte';
	import SecretDialog from '#lib/components/SecretDialog.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import IconButton from '#lib/components/IconButton.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import DateInput from '#lib/components/DateInput.svelte';

	type Token = components['schemas']['TokenOut'];
	type Scope = components['schemas']['TokenScope'];

	// API tokens: for scripts and tools, never for this UI. The token itself is shown once.
	let tokens = $state<Token[] | null>(null);
	let problem = $state<string | null>(null);
	let creating = $state(false);
	let name = $state('');
	let scope = $state<Scope>('read');
	let expires = $state('');
	let created = $state<string | null>(null);
	let revoking = $state<Token | null>(null);

	async function load() {
		problem = null;
		try {
			tokens = await unwrap(api.GET('/api/v1/auth/tokens'));
		} catch (failure) {
			problem = describeError(failure);
		}
	}

	onMount(load);

	function openCreate() {
		name = '';
		scope = 'read';
		expires = '';
		creating = true;
	}

	async function create() {
		const token = await unwrap(
			api.POST('/api/v1/auth/tokens', {
				body: {
					name: name.trim(),
					scope,
					// The token works through the end of the chosen day, in this browser's zone.
					expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null
				}
			})
		);
		created = token.token;
		await load();
	}

	async function revoke() {
		if (!revoking) return;
		await unwrap(api.DELETE('/api/v1/auth/tokens/{id}', { params: { path: { id: revoking.id } } }));
		toast.success(m.token_revoked());
		await load().catch(reportError);
	}

	const scopes = [
		{ value: 'read', label: m.token_scope_read() },
		{ value: 'read_write', label: m.token_scope_read_write() }
	];
	const today = new Date().toLocaleDateString('sv');
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>{m.token_title()}</Card.Title>
		<Card.Description>{m.token_hint()}</Card.Description>
		<Card.Action><Button onclick={openCreate}>{m.token_new()}</Button></Card.Action>
	</Card.Header>
	<Card.Content>
		{#if problem}
			<LoadProblem {problem} onretry={load} />
		{:else if tokens === null}
			<Loading />
		{:else if tokens.length === 0}
			<p class="text-muted-foreground">{m.token_none()}</p>
		{:else}
			<ul class="divide-y">
				{#each tokens as token (token.id)}
					<li class="flex items-center gap-3 py-3">
						<div class="min-w-0 flex-1">
							<p class="truncate font-medium">{token.name}</p>
							<p class="text-sm text-muted-foreground">
								{token.last_used_at
									? m.token_used({
											time: formatDate(token.last_used_at, {
												dateStyle: 'short',
												timeStyle: 'short'
											})
										})
									: m.token_never_used()}
								·
								{token.expires_at
									? m.token_expires({ time: formatDate(token.expires_at, { dateStyle: 'short' }) })
									: m.token_no_expiry()}
							</p>
						</div>
						<Badge variant="note">
							{token.scope === 'read' ? m.token_scope_read() : m.token_scope_read_write()}
						</Badge>
						<IconButton
							label={m.token_revoke_named({ name: token.name })}
							onclick={() => (revoking = token)}
						>
							<Trash aria-hidden="true" />
						</IconButton>
					</li>
				{/each}
			</ul>
		{/if}
	</Card.Content>
</Card.Root>

<FormDialog
	bind:open={creating}
	title={m.token_new()}
	submitLabel={m.token_create()}
	disabled={name.trim() === ''}
	action={create}
>
	<Field.Field>
		<Field.Label for="token-name">{m.field_name()}</Field.Label>
		<Input id="token-name" bind:value={name} maxlength={100} required />
	</Field.Field>
	<Field.Field>
		<Field.Label for="token-scope">{m.token_scope()}</Field.Label>
		<Select
			id="token-scope"
			value={scope}
			onchange={(value) => (scope = value as Scope)}
			options={scopes}
		/>
		<Field.Description>{m.token_scope_hint()}</Field.Description>
	</Field.Field>
	<Field.Field>
		<Field.Label for="token-expires">{m.token_expires_on()}</Field.Label>
		<DateInput id="token-expires" label={m.token_expires_on()} min={today} bind:value={expires} />
		<Field.Description>{m.token_expires_hint()}</Field.Description>
	</Field.Field>
</FormDialog>

<SecretDialog
	secret={created}
	title={m.token_created_title()}
	description={m.token_created_hint()}
	onclose={() => (created = null)}
/>

<ConfirmDialog
	bind:open={() => revoking !== null, (open) => !open && (revoking = null)}
	title={m.token_revoke_named({ name: revoking?.name ?? '' })}
	description={m.token_revoke_confirm()}
	confirmLabel={m.token_revoke()}
	onconfirm={revoke}
/>
