<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import ChipInput from '#lib/components/ChipInput.svelte';
	import HintLabel from '#lib/components/HintLabel.svelte';
	import IdentifiersEditor from '#lib/components/IdentifiersEditor.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { describeError } from '#lib/errors.ts';
	import {
		type IdentifierRow,
		NAMING_KINDS,
		numbersOf,
		PERSON_KINDS,
		rowsOf
	} from '#lib/identifiers.ts';
	import type { Contact, Tag } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import DateInput from '#lib/components/DateInput.svelte';

	// A user's profile (Tobi, 21.10.2026): the display name others see, and what only the user
	// and admins see: other names, birth date, e-mail and the person's own numbers. Found in a
	// document, they tell whose it is; none of it goes to the language model. With them the
	// user's numbers at contacts (issue #82): private too, entered, taken over or declined here.
	// `userId` null: the caller's own (settings); else an admin edits another user's (user
	// management).
	type Profile = components['schemas']['ProfileOut'];

	let { userId = null, onsaved }: { userId?: string | null; onsaved?: () => void } = $props();

	const uid = $props.id();
	let profile = $state<Profile | null>(null);
	let displayName = $state('');
	let aliases = $state<string[]>([]);
	let birthDate = $state('');
	let email = $state('');
	let identifiers = $state<IdentifierRow[]>([]);
	let opened = $state<number | null>(null);
	let numbers = $state<IdentifierRow[]>([]);
	let openedNumber = $state<number | null>(null);
	let contacts = $state<Contact[]>([]);
	let topics = $state<Tag[]>([]);
	let problem = $state<string | null>(null);
	let busy = $state(false);

	function show(loaded: Profile) {
		profile = loaded;
		displayName = loaded.display_name ?? '';
		aliases = [...loaded.aliases];
		birthDate = loaded.birth_date ?? '';
		email = loaded.email ?? '';
		identifiers = rowsOf(loaded.identifiers);
		numbers = rowsOf(loaded.numbers);
	}

	async function load() {
		try {
			const [loaded, contactList, tags] = await Promise.all([
				unwrap(
					userId === null
						? api.GET('/api/v1/auth/me/profile')
						: api.GET('/api/v1/users/{id}/profile', { params: { path: { id: userId } } })
				),
				unwrap(api.GET('/api/v1/contacts')),
				unwrap(api.GET('/api/v1/tags'))
			]);
			contacts = contactList;
			topics = tags.filter((tag) => tag.scope === 'topic');
			show(loaded);
		} catch (error) {
			problem = describeError(error);
		}
	}

	function topicsOf(contact: string): readonly string[] {
		return contacts.find((item) => item.id === contact)?.topic_ids ?? [];
	}

	onMount(load);

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
				.map((item) => ({ kind: item.kind, value: item.value.trim() })),
			...numbersOf(numbers, topicsOf)
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
		<LoadProblem {problem} onretry={load} />
	{:else}
		<Loading class="text-sm" />
	{/if}
{:else}
	<form class="flex flex-col gap-4" onsubmit={save}>
		<Field.Field>
			<HintLabel
				for="{uid}-name"
				label={m.profile_display_name()}
				hint={m.profile_display_name_hint()}
				hintId="{uid}-name-hint"
			/>
			<Input
				id="{uid}-name"
				bind:value={displayName}
				maxlength={150}
				autocomplete="name"
				aria-describedby="{uid}-name-hint"
			/>
		</Field.Field>
		<Field.Field>
			<HintLabel
				id="{uid}-aliases-label"
				label={m.profile_aliases()}
				hint={m.profile_aliases_hint()}
				hintId="{uid}-aliases-hint"
			/>
			<ChipInput
				bind:values={aliases}
				labelledby="{uid}-aliases-label"
				describedby="{uid}-aliases-hint"
				addLabel={m.profile_alias_chip()}
				inputLabel={m.profile_alias_input()}
			/>
		</Field.Field>
		<div class="grid gap-4 sm:grid-cols-2">
			<Field.Field>
				<Field.Label for="{uid}-birth">{m.profile_birth_date()}</Field.Label>
				<DateInput id="{uid}-birth" label={m.profile_birth_date()} bind:value={birthDate} />
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
		<Field.Field>
			<Field.Label>{m.profile_numbers()}</Field.Label>
			<IdentifiersEditor
				bind:rows={numbers}
				bind:opened={openedNumber}
				kinds={NAMING_KINDS}
				{topics}
				{contacts}
				hint={m.profile_numbers_hint()}
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
