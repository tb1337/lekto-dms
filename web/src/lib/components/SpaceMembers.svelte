<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import Select from '#lib/components/Select.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { reportError } from '#lib/errors.ts';
	import {
		spaceLabel,
		userLabel,
		userName,
		type Space,
		type UserName
	} from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';

	type Role = components['schemas']['SpaceRole'];

	// Who is in a space: readers see its green documents, editors every document and the space's
	// rules, members and name. The user of a personal space always edits it, and a space keeps one
	// editor; the API refuses the rest (422).
	let {
		open = $bindable(false),
		space,
		users,
		onchanged
	}: {
		open?: boolean;
		space: Space;
		users: readonly UserName[];
		onchanged: () => void;
	} = $props();

	let userId = $state('');
	let role = $state<Role>('read');
	let busy = $state(false);

	const label = $derived(spaceLabel(space, users, session.user?.id));
	// Members come with their names, a deactivated one too (whom the users list hides).
	const name = (id: string) => {
		const member = space.members.find((entry) => entry.user_id === id);
		return member ? userLabel(member) : userName(users, id);
	};
	const editors = $derived(space.members.filter((member) => member.role === 'edit').length);
	// The user of a personal space stays an editor; the last editor of a space stays one.
	const fixed = (member: Space['members'][number]) =>
		member.user_id === space.personal_of || (member.role === 'edit' && editors === 1);
	const candidates = $derived(
		users.filter(
			(user) => user.active !== false && !space.members.some((member) => member.user_id === user.id)
		)
	);
	const roles = $derived([
		{ value: 'read', label: m.space_role_read() },
		{ value: 'edit', label: m.space_role_edit() }
	]);

	async function set(id: string, next: Role) {
		busy = true;
		try {
			await unwrap(
				api.PUT('/api/v1/spaces/{id}/members/{user_id}', {
					params: { path: { id: space.id, user_id: id } },
					body: { role: next }
				})
			);
			toast.success(m.members_saved());
			onchanged();
			userId = '';
		} catch (error) {
			reportError(error);
		} finally {
			busy = false;
		}
	}

	async function remove(id: string) {
		busy = true;
		try {
			await unwrap(
				api.DELETE('/api/v1/spaces/{id}/members/{user_id}', {
					params: { path: { id: space.id, user_id: id } }
				})
			);
			toast.success(m.members_removed());
			onchanged();
		} catch (error) {
			reportError(error);
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-w-lg">
		<Dialog.Header>
			<Dialog.Title>{m.members_title({ name: label })}</Dialog.Title>
			<Dialog.Description>
				{#if space.personal_of !== null}
					{m.members_personal_hint({ name: name(space.personal_of) })}
				{/if}
				{m.members_hint()}
			</Dialog.Description>
		</Dialog.Header>

		<ul class="flex flex-col gap-2">
			{#each space.members as member (member.user_id)}
				<li class="flex items-center gap-2">
					<span class="min-w-0 flex-1 truncate">{userLabel(member)}</span>
					{#if fixed(member)}
						<Badge variant="secondary">{m.space_role_edit()}</Badge>
					{:else if !member.active}
						<!-- A deactivated member takes no new role; an editor removes them. -->
						<Badge variant="outline">{m.user_inactive()}</Badge>
						<Button
							variant="ghost"
							size="icon"
							disabled={busy}
							aria-label={m.members_remove({ name: userLabel(member) })}
							onclick={() => remove(member.user_id)}
						>
							<X aria-hidden="true" />
						</Button>
					{:else}
						<Select
							aria-label={m.members_role_of({ name: name(member.user_id) })}
							value={member.role}
							options={roles}
							disabled={busy}
							onchange={(value) => set(member.user_id, value as Role)}
							class="h-10 w-40"
						/>
						<Button
							variant="ghost"
							size="icon"
							disabled={busy}
							aria-label={m.members_remove({ name: name(member.user_id) })}
							onclick={() => remove(member.user_id)}
						>
							<X aria-hidden="true" />
						</Button>
					{/if}
				</li>
			{/each}
		</ul>

		{#if candidates.length > 0}
			<div class="flex flex-col gap-3 border-t pt-4">
				<Field.Field>
					<Field.Label for="member-user">{m.members_add()}</Field.Label>
					<Select
						id="member-user"
						bind:value={userId}
						options={[
							{ value: '', label: m.members_choose_user() },
							...candidates.map((user) => ({ value: user.id, label: userLabel(user) }))
						]}
					/>
				</Field.Field>
				<Field.Field>
					<Field.Label for="member-role">{m.members_role()}</Field.Label>
					<Select
						id="member-role"
						value={role}
						options={roles}
						onchange={(value) => (role = value as Role)}
					/>
				</Field.Field>
				<div>
					<Button disabled={busy || !userId} onclick={() => set(userId, role)}>
						{m.members_grant()}
					</Button>
				</div>
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>
