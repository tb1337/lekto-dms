<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import ConfirmFooter from '#lib/components/ConfirmFooter.svelte';
	import Select from '#lib/components/Select.svelte';
	import * as AlertDialog from '#lib/components/ui/alert-dialog/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import {
		choicesOf,
		editorOptions,
		initialDecisions,
		moveTargets,
		removalBody,
		settled,
		type BlockingSpace,
		type Decision,
		type How
	} from '#lib/user-removal.ts';

	// Deleting a user (Tobi, 22.10.2026): the spaces they leave behind are decided here, each
	// with a click, and all goes in one request; with none, it is a plain confirmation.
	let {
		open = $bindable(false),
		userId,
		username,
		ondeleted
	}: { open?: boolean; userId: string; username: string; ondeleted: () => void } = $props();

	let blocking = $state<BlockingSpace[] | null>(null);
	let lookup = $state<Lookup | null>(null);
	let decisions = $state<Record<string, Decision>>({});
	let problem = $state<string | null>(null);
	let busy = $state(false);

	async function load() {
		[blocking, problem] = [null, null];
		try {
			const [removal, loaded] = await Promise.all([
				unwrap(api.GET('/api/v1/users/{id}/removal', { params: { path: { id: userId } } })),
				loadLookup()
			]);
			[blocking, lookup] = [removal.blocking_spaces, loaded];
			decisions = initialDecisions(removal.blocking_spaces);
		} catch (error) {
			problem = describeError(error);
		}
	}

	$effect(() => {
		if (open) void load();
	});

	const targets = $derived(
		blocking && lookup
			? moveTargets(lookup.spaces, lookup.users, userId, blocking, session.user?.id)
			: []
	);
	const editors = $derived(lookup ? editorOptions(lookup.users, userId) : []);
	const ready = $derived(blocking !== null && settled(blocking, decisions));

	const HOW_LABELS: Record<How, () => string> = {
		remove: () => m.user_delete_remove(),
		move_to: () => m.user_delete_move(),
		editor: () => m.user_delete_editor()
	};

	function title(space: BlockingSpace): string {
		const name = space.personal ? m.user_delete_personal({ name: username }) : space.name;
		return m.user_delete_space({ name, count: space.documents });
	}

	async function confirm(event: Event) {
		event.preventDefault();
		if (!blocking || !ready) return;
		busy = true;
		try {
			await unwrap(
				api.DELETE('/api/v1/users/{id}', {
					params: { path: { id: userId } },
					body: removalBody(blocking, decisions)
				})
			);
			toast.success(m.user_deleted());
			open = false;
			ondeleted();
		} catch (error) {
			reportError(error);
			await load(); // something changed meanwhile: decide again
		} finally {
			busy = false;
		}
	}
</script>

<AlertDialog.Root bind:open>
	<AlertDialog.Content class="max-w-lg">
		<AlertDialog.Header>
			<AlertDialog.Title>{m.user_delete()}</AlertDialog.Title>
			<AlertDialog.Description>{m.user_delete_confirm()}</AlertDialog.Description>
		</AlertDialog.Header>
		{#if problem}
			<p class="text-destructive" role="alert">{problem}</p>
		{:else if blocking === null}
			<p class="text-muted-foreground">{m.loading()}</p>
		{:else if blocking.length > 0}
			<div class="flex max-h-[55vh] flex-col gap-4 overflow-auto">
				<p class="text-sm">{m.user_delete_spaces()}</p>
				{#each blocking as space (space.space_id)}
					{@const decision = decisions[space.space_id]}
					<fieldset class="flex flex-col gap-2 rounded-xl border p-3">
						<legend class="px-1 text-sm font-medium">{title(space)}</legend>
						{#if choicesOf(space).length > 1}
							<Select
								aria-label={m.user_delete_how({ name: title(space) })}
								value={decision?.how ?? ''}
								options={choicesOf(space).map((how) => ({ value: how, label: HOW_LABELS[how]() }))}
								onchange={(how) => (decisions[space.space_id] = { how: how as How, target: '' })}
							/>
						{:else}
							<span class="text-sm text-muted-foreground">{HOW_LABELS[choicesOf(space)[0]]()}</span>
						{/if}
						{#if decision?.how === 'move_to'}
							<Select
								aria-label={m.user_delete_choose_space()}
								value={decision.target}
								options={[{ value: '', label: m.user_delete_choose_space() }, ...targets]}
								onchange={(target) => (decisions[space.space_id] = { how: 'move_to', target })}
							/>
						{:else if decision?.how === 'editor'}
							<Select
								aria-label={m.user_delete_choose_user()}
								value={decision.target}
								options={[{ value: '', label: m.user_delete_choose_user() }, ...editors]}
								onchange={(target) => (decisions[space.space_id] = { how: 'editor', target })}
							/>
						{/if}
					</fieldset>
				{/each}
			</div>
		{/if}
		<ConfirmFooter label={m.user_delete()} {busy} disabled={!ready} onconfirm={confirm} />
	</AlertDialog.Content>
</AlertDialog.Root>
