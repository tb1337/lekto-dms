<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import IdentifiersEditor from '#lib/components/IdentifiersEditor.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { type IdentifierRow, PERSON_KINDS, rowsOf } from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A user's profile (Tobi, 21.10.2026): the display name others see, and what only the user
	// and admins see: other names, birth date, e-mail and the person's own numbers. Found in a
	// document, they tell whose it is; none of it goes to the language model. `userId` null: the
	// caller's own (settings); else an admin edits another user's (user management).
	type Profile = components['schemas']['ProfileOut'];

	let { userId = null, onsaved }: { userId?: string | null; onsaved?: () => void } = $props();

	const uid = $props.id();
	let profile = $state<Profile | null>(null);
	let displayName = $state('');
	let aliases = $state<string[]>([]);
	let alias = $state('');
	let birthDate = $state('');
	let email = $state('');
	let identifiers = $state<IdentifierRow[]>([]);
	let opened = $state<number | null>(null);
	let problem = $state<string | null>(null);
	let busy = $state(false);

	function show(loaded: Profile) {
		profile = loaded;
		displayName = loaded.display_name ?? '';
		aliases = [...loaded.aliases];
		birthDate = loaded.birth_date ?? '';
		email = loaded.email ?? '';
		identifiers = rowsOf(loaded.identifiers);
	}

	async function load() {
		try {
			show(
				await unwrap(
					userId === null
						? api.GET('/api/v1/auth/me/profile')
						: api.GET('/api/v1/users/{id}/profile', { params: { path: { id: userId } } })
				)
			);
		} catch (error) {
			problem = describeError(error);
		}
	}

	onMount(load);

	function addAlias() {
		const name = alias.trim();
		if (name !== '' && !aliases.some((item) => item.toLowerCase() === name.toLowerCase())) {
			aliases = [...aliases, name];
		}
		alias = '';
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		problem = null;
		const body = {
			display_name: displayName.trim() || null,
			aliases,
			birth_date: birthDate || null,
			email: email.trim() || null,
			identifiers: identifiers
				.filter((item) => item.value.trim() !== '')
				.map((item) => ({ kind: item.kind, value: item.value.trim() }))
		};
		try {
			show(
				await unwrap(
					userId === null
						? api.PATCH('/api/v1/auth/me/profile', { body })
						: api.PATCH('/api/v1/users/{id}/profile', {
								params: { path: { id: userId } },
								body
							})
				)
			);
			toast.success(m.profile_saved());
			onsaved?.();
		} catch (error) {
			problem = describeError(error);
		} finally {
			busy = false;
		}
	}
</script>

{#if profile === null}
	{#if problem}
		<p class="text-sm text-destructive" role="alert">{problem}</p>
	{:else}
		<p class="text-sm text-muted-foreground">{m.loading()}</p>
	{/if}
{:else}
	<form class="flex flex-col gap-4" onsubmit={save}>
		<p class="text-sm text-muted-foreground">{m.profile_hint()}</p>
		<Field.Field>
			<Field.Label for="{uid}-name">{m.profile_display_name()}</Field.Label>
			<Input id="{uid}-name" bind:value={displayName} maxlength={150} autocomplete="name" />
			<Field.Description>{m.profile_display_name_hint()}</Field.Description>
		</Field.Field>
		<Field.Field>
			<Field.Label for="{uid}-alias">{m.profile_aliases()}</Field.Label>
			{#if aliases.length > 0}
				<ul class="flex flex-wrap gap-1.5">
					{#each aliases as item (item)}
						<li
							class="inline-flex items-center gap-1 rounded-full bg-secondary py-0.5 pr-1 pl-3 text-sm"
						>
							{item}
							<Button
								type="button"
								variant="ghost"
								size="icon"
								class="size-6"
								aria-label={m.profile_alias_remove({ name: item })}
								onclick={() => (aliases = aliases.filter((other) => other !== item))}
							>
								<X class="size-3.5" aria-hidden="true" />
							</Button>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="flex gap-2">
				<Input
					id="{uid}-alias"
					bind:value={alias}
					maxlength={150}
					onkeydown={(event) => {
						if (event.key !== 'Enter') return;
						event.preventDefault();
						addAlias();
					}}
				/>
				<Button type="button" variant="outline" onclick={addAlias} disabled={alias.trim() === ''}>
					{m.profile_alias_add()}
				</Button>
			</div>
			<Field.Description>{m.profile_aliases_hint()}</Field.Description>
		</Field.Field>
		<div class="grid gap-4 sm:grid-cols-2">
			<Field.Field>
				<Field.Label for="{uid}-birth">{m.profile_birth_date()}</Field.Label>
				<Input id="{uid}-birth" type="date" bind:value={birthDate} />
			</Field.Field>
			<Field.Field>
				<Field.Label for="{uid}-email">{m.profile_email()}</Field.Label>
				<Input id="{uid}-email" type="email" bind:value={email} autocomplete="email" />
			</Field.Field>
		</div>
		<Field.Field>
			<Field.Label>{m.profile_identifiers()}</Field.Label>
			<IdentifiersEditor
				bind:rows={identifiers}
				bind:opened
				kinds={PERSON_KINDS}
				hint={m.profile_identifiers_hint()}
			/>
		</Field.Field>
		{#if problem}
			<p class="text-sm text-destructive" role="alert">{problem}</p>
		{/if}
		<div>
			<Button type="submit" disabled={busy}>{m.save()}</Button>
		</div>
	</form>
{/if}
