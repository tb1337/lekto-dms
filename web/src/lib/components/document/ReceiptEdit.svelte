<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { localMinute } from '#lib/file-passport.ts';
	import { m } from '#lib/paraglide/messages.js';
	import IconButton from '#lib/components/IconButton.svelte';

	// When the document came in, set anew at its milestone (Tobi, 21.10.2026): to the minute,
	// in local time, never ahead. It confirms nothing and no rules run.
	let {
		documentId,
		value,
		onchanged
	}: { documentId: string; value: string; onchanged?: () => void } = $props();

	const id = $props.id();
	let open = $state(false);
	let draft = $state('');
	let latest = $state('');
	let problem = $state<string | null>(null);
	let saving = $state(false);

	function opened(next: boolean) {
		if (!next) return;
		draft = localMinute(new Date(value));
		latest = localMinute(new Date());
		problem = null;
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!draft) return;
		saving = true;
		problem = null;
		try {
			await unwrap(
				api.PATCH('/api/v1/documents/{id}', {
					params: { path: { id: documentId } },
					body: { created_at: new Date(draft).toISOString() }
				})
			);
			open = false;
			onchanged?.();
		} catch (error) {
			problem = describeError(error);
		} finally {
			saving = false;
		}
	}
</script>

<Popover.Root bind:open onOpenChange={opened}>
	<Popover.Trigger>
		{#snippet child({ props })}
			<IconButton
				{...props}
				size="sm"
				class="text-muted-foreground"
				label={m.files_received_edit()}
			>
				<Pencil aria-hidden="true" />
			</IconButton>
		{/snippet}
	</Popover.Trigger>
	<Popover.Content collisionPadding={8} role="dialog" aria-labelledby="{id}-title" class="w-72">
		<form class="flex flex-col gap-3" onsubmit={save}>
			<label class="flex flex-col gap-1.5">
				<span id="{id}-title" class="text-sm font-semibold">{m.files_received_label()}</span>
				<Input type="datetime-local" bind:value={draft} max={latest} required />
			</label>
			{#if problem}
				<Field.Error>{problem}</Field.Error>
			{/if}
			<div class="flex justify-end gap-2">
				<Button type="button" variant="ghost" size="sm" onclick={() => (open = false)}>
					{m.cancel()}
				</Button>
				<Button type="submit" size="sm" disabled={saving || !draft}>{m.save()}</Button>
			</div>
		</form>
	</Popover.Content>
</Popover.Root>
