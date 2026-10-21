<script lang="ts">
	import Upload from '@lucide/svelte/icons/upload';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { reportError } from '#lib/errors.ts';
	import { ACCEPT, intakeOf, readDrop, type Intake } from '#lib/intake.ts';
	import { spacesFor } from '#lib/permissions.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { uploads } from '#lib/upload.svelte.ts';
	import { spaceLabel, type Space, type UserName } from '#lib/masterdata.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// Upload with a choice: the space, and for admins the owner. Files are chosen (on a phone the
	// system's picker offers the camera and the photos) or dropped here, folders too; then the
	// dialog closes and the inbox shows what came of them.
	let {
		open = $bindable(false),
		spaces,
		users
	}: { open?: boolean; spaces: readonly Space[]; users: readonly UserName[] } = $props();

	// Empty: the caller. The duplicate check, the default space and the write access are the
	// owner's.
	let ownerId = $state('');
	let spaceId = $state('');
	let over = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	const owner = $derived(
		ownerId ? (users.find((user) => user.id === ownerId) ?? null) : (session.user ?? null)
	);
	const owners = $derived([
		{ value: '', label: m.upload_owner_me({ name: session.user?.username ?? '' }) },
		...users
			.filter((user) => user.id !== session.user?.id && user.active !== false)
			.map((user) => ({ value: user.id, label: user.username }))
	]);
	// Uploads go into the owner's own spaces or those shared with them for writing (an admin's
	// own: any); empty = the owner's default.
	const choices = $derived([
		{
			value: '',
			label: ownerId
				? m.upload_default_space_of({ owner: owner?.username ?? '' })
				: m.upload_default_space()
		},
		...spacesFor(spaces, owner, session.user).map((space) => ({
			value: space.id,
			label: spaceLabel(space, users, session.user?.id)
		}))
	]);

	// Another owner's spaces differ: a space chosen for the one before may not be theirs.
	$effect(() => {
		if (spaceId && !choices.some((choice) => choice.value === spaceId)) spaceId = '';
	});

	function take(intake: Intake) {
		if (intake.files.length + intake.skipped.length === 0) return;
		uploads.add(intake, { spaceId: spaceId || null, owner: ownerId || null });
		open = false;
	}

	function chosen() {
		if (input?.files) take(intakeOf(input.files));
		if (input) input.value = '';
	}

	function drop(event: DragEvent) {
		event.preventDefault();
		// The inbox page takes drops itself; this one goes where the dialog says.
		event.stopPropagation();
		over = false;
		if (event.dataTransfer) readDrop(event.dataTransfer).then(take, reportError);
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-w-xl">
		<Dialog.Header>
			<Dialog.Title>{m.upload_title()}</Dialog.Title>
			<Dialog.Description>{m.upload_hint()}</Dialog.Description>
		</Dialog.Header>

		{#if session.isAdmin}
			<Field.Field>
				<Field.Label for="upload-owner">{m.upload_owner()}</Field.Label>
				<Select id="upload-owner" bind:value={ownerId} options={owners} />
			</Field.Field>
		{/if}
		<Field.Field>
			<Field.Label for="upload-space">{m.upload_space()}</Field.Label>
			<Select id="upload-space" bind:value={spaceId} options={choices} />
		</Field.Field>

		<div
			role="presentation"
			ondragover={(event) => {
				event.preventDefault();
				event.stopPropagation();
				over = true;
			}}
			ondragleave={() => (over = false)}
			ondrop={drop}
			class={cn(
				'flex flex-col items-center gap-3 rounded-2xl border border-dashed px-6 py-10 text-center text-muted-foreground transition-colors',
				over && 'border-primary bg-secondary'
			)}
		>
			<Upload class="size-7" aria-hidden="true" />
			<p class="max-sm:hidden">{m.upload_drop()}</p>
			<Button variant="outline" class="h-11 sm:h-10" onclick={() => input?.click()}>
				{m.upload_choose()}
			</Button>
			<input
				bind:this={input}
				type="file"
				multiple
				accept={ACCEPT}
				class="sr-only"
				tabindex="-1"
				aria-label={m.upload_choose()}
				onchange={chosen}
			/>
		</div>
	</Dialog.Content>
</Dialog.Root>
