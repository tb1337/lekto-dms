<script lang="ts">
	import Upload from '@lucide/svelte/icons/upload';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { reportError } from '#lib/errors.ts';
	import { ACCEPT, intakeOf, readDrop, type Intake } from '#lib/intake.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { uploads } from '#lib/upload.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// Upload into the personal space (Tobi, 21.10.2026: no choice of space; Lekto suggests where a
	// document belongs). Files are chosen (on a phone the system's picker offers the camera and the
	// photos) or dropped here, folders too; then the dialog closes and the inbox shows what came of
	// them.
	let { open = $bindable(false) }: { open?: boolean } = $props();

	let over = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	function take(intake: Intake) {
		if (intake.files.length + intake.skipped.length === 0) return;
		uploads.add(intake);
		open = false;
	}

	function chosen() {
		if (input?.files) take(intakeOf(input.files));
		if (input) input.value = '';
	}

	function drop(event: DragEvent) {
		event.preventDefault();
		// The inbox page takes drops itself; this one is the dialog's.
		event.stopPropagation();
		over = false;
		if (event.dataTransfer) readDrop(event.dataTransfer).then(take, reportError);
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content size="lg">
		<Dialog.Header>
			<Dialog.Title>{m.upload_title()}</Dialog.Title>
			<Dialog.Description>{m.upload_hint()}</Dialog.Description>
		</Dialog.Header>

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
