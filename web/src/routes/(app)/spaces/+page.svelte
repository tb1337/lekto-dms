<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import LogOut from '@lucide/svelte/icons/log-out';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import UserRound from '@lucide/svelte/icons/user-round';
	import Users from '@lucide/svelte/icons/users';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import EditButton from '#lib/components/EditButton.svelte';
	import SpaceMembers from '#lib/components/SpaceMembers.svelte';
	import SpaceDialog from '#lib/components/SpaceDialog.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { latest } from '#lib/latest.ts';
	import { spaceLabel, userLabel, type Space, type UserName } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import {
		canChooseMembers,
		canDescribeSpace,
		canLeaveSpace,
		canManageSpace
	} from '#lib/permissions.ts';
	import { scope } from '#lib/scope.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	let spaces = $state<Space[] | null>(null);
	let users = $state<UserName[]>([]);
	let problem = $state<string | null>(null);
	let creating = $state(false);
	let editing = $state<Space | null>(null);
	let removing = $state<Space | null>(null);
	let leaving = $state<Space | null>(null);
	let choosing = $state<string | null>(null);

	const me = $derived(session.user?.id);
	const isMember = (space: Space) => space.members.some((member) => member.user_id === me);
	// The caller's spaces, their personal one first; with "Alle Nutzer einbeziehen" an admin
	// also gets every other space (the list follows the reach, `scope`).
	const mine = $derived(
		(spaces ?? [])
			.filter(isMember)
			.toSorted((a, b) => Number(b.personal_of === me) - Number(a.personal_of === me))
	);
	const others = $derived(scope.allUsers ? (spaces ?? []).filter((space) => !isMember(space)) : []);
	const chosen = $derived(spaces?.find((space) => space.id === choosing) ?? null);
	const label = (space: Space) => spaceLabel(space, users, me);
	const memberLine = (space: Space) =>
		space.members
			.filter((member) => member.user_id !== me)
			.map((member) =>
				member.role === 'read'
					? m.space_member_reads({ name: userLabel(member) })
					: userLabel(member)
			)
			.join(', ');

	// An answer overtaken by a later load (the reach switched twice) is dropped.
	const begin = latest();
	async function load() {
		const current = begin();
		try {
			const [found, known] = await Promise.all([
				unwrap(api.GET('/api/v1/spaces', { params: { query: { all_users: scope.query } } })),
				unwrap(api.GET('/api/v1/users'))
			]);
			if (!current()) return;
			[spaces, users, problem] = [found, known, null];
		} catch (error) {
			if (current()) problem = describeError(error);
		}
	}

	// Again when an admin switches the reach in the user menu.
	$effect(() => {
		void scope.allUsers;
		untrack(() => void load());
	});

	async function create(name: string, description: string) {
		await unwrap(api.POST('/api/v1/spaces', { body: { name, description: description || null } }));
		toast.success(m.space_created());
		await load();
	}

	// A personal space keeps its name: only its description goes.
	async function change(name: string, description: string) {
		if (!editing) return;
		const body =
			editing.personal_of === null
				? { name, description: description || null }
				: { description: description || null };
		await unwrap(api.PATCH('/api/v1/spaces/{id}', { params: { path: { id: editing.id } }, body }));
		toast.success(m.space_saved());
		await load();
	}

	async function leave() {
		if (!leaving || !me) return;
		await unwrap(
			api.DELETE('/api/v1/spaces/{id}/members/{user_id}', {
				params: { path: { id: leaving.id, user_id: me } }
			})
		);
		toast.success(m.space_left());
		await load();
	}

	async function remove() {
		if (!removing) return;
		await unwrap(api.DELETE('/api/v1/spaces/{id}', { params: { path: { id: removing.id } } }));
		toast.success(m.space_deleted());
		await load();
	}
</script>

<svelte:head><title>{m.nav_spaces()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_spaces()}</h1>
		<Button onclick={() => (creating = true)}>
			<Plus aria-hidden="true" />
			{m.space_new()}
		</Button>
	</div>

	{#if problem}
		<LoadProblem {problem} onretry={load} />
	{:else if !spaces}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else}
		<section class="flex flex-col gap-3" aria-labelledby="own-spaces">
			<h2 id="own-spaces" class="text-lg font-semibold">{m.spaces_own()}</h2>
			<ul class="flex flex-col gap-2">
				{#each mine as space (space.id)}
					{@render row(space)}
				{/each}
			</ul>
		</section>

		{#if others.length > 0}
			<section class="flex flex-col gap-3" aria-labelledby="other-spaces">
				<h2 id="other-spaces" class="text-lg font-semibold">{m.spaces_others()}</h2>
				<ul class="flex flex-col gap-2">
					{#each others as space (space.id)}
						{@render row(space)}
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
</div>

{#snippet row(space: Space)}
	{@const Icon = space.personal_of === null ? Archive : UserRound}
	{@const members = memberLine(space)}
	<li class="flex flex-wrap items-center gap-3 rounded-2xl border bg-card p-4">
		<Icon class="size-5 text-muted-foreground" aria-hidden="true" />
		<div class="flex min-w-0 flex-1 flex-col gap-1">
			<span class="flex flex-wrap items-center gap-2 font-medium">
				<span class="truncate">{label(space)}</span>
				{#if space.personal_of !== null && space.personal_of !== me}
					<Badge variant="secondary">{m.space_personal()}</Badge>
				{/if}
				{#if isMember(space) && space.role === 'read'}
					<Badge variant="outline">{m.space_role_read()}</Badge>
				{/if}
			</span>
			{#if space.description}
				<span class="text-sm break-words">{space.description}</span>
			{/if}
			<span class="text-sm text-muted-foreground">
				{members ? m.space_members_line({ names: members }) : m.space_only_you()}
			</span>
		</div>
		<div class="flex gap-1">
			{#if canChooseMembers(space, session.user)}
				<Button
					variant="ghost"
					size="icon"
					aria-label={m.space_members({ name: label(space) })}
					onclick={() => (choosing = space.id)}
				>
					<Users aria-hidden="true" />
				</Button>
			{/if}
			{#if canLeaveSpace(space, session.user)}
				<Button
					variant="ghost"
					size="icon"
					aria-label={m.space_leave({ name: label(space) })}
					onclick={() => (leaving = space)}
				>
					<LogOut aria-hidden="true" />
				</Button>
			{/if}
			{#if canManageSpace(space, session.user)}
				<Button
					variant="ghost"
					size="icon"
					aria-label={m.space_delete({ name: space.name })}
					onclick={() => (removing = space)}
				>
					<Trash2 aria-hidden="true" />
				</Button>
			{/if}
		</div>
		{#if canDescribeSpace(space, session.user)}
			<EditButton label={m.space_edit({ name: label(space) })} onclick={() => (editing = space)} />
		{/if}
	</li>
{/snippet}

<SpaceDialog
	bind:open={creating}
	title={m.space_new()}
	submitLabel={m.create()}
	onsubmit={create}
/>
<SpaceDialog
	bind:open={() => editing !== null, (open) => !open && (editing = null)}
	title={m.space_edit({ name: editing ? label(editing) : '' })}
	initialName={editing?.name ?? ''}
	initialDescription={editing?.description ?? ''}
	named={editing?.personal_of === null}
	onsubmit={change}
/>
<ConfirmDialog
	bind:open={() => removing !== null, (open) => !open && (removing = null)}
	title={m.space_delete({ name: removing?.name ?? '' })}
	description={m.space_delete_confirm()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
<ConfirmDialog
	bind:open={() => leaving !== null, (open) => !open && (leaving = null)}
	title={m.space_leave({ name: leaving ? label(leaving) : '' })}
	description={m.space_leave_confirm()}
	confirmLabel={m.space_leave_action()}
	onconfirm={leave}
/>
{#if chosen}
	<SpaceMembers
		bind:open={() => choosing !== null, (open) => !open && (choosing = null)}
		space={chosen}
		{users}
		onchanged={load}
	/>
{/if}
