<script lang="ts">
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import Copy from '@lucide/svelte/icons/copy';
	import Upload from '@lucide/svelte/icons/upload';
	import X from '@lucide/svelte/icons/x';
	import { BASE } from '#lib/base.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Progress } from '#lib/components/ui/progress/index.ts';
	import type { SkipReason } from '#lib/intake.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { uploads } from '#lib/upload.svelte.ts';
	import * as Card from '#lib/components/ui/card/index.ts';

	// What came of the uploads, until dismissed (in this browser only): "12 uploaded,
	// 1 duplicate, 3 skipped", the progress while files are on their way, and each duplicate
	// (with the document already there), skipped file (with the reason) and failure. A screen
	// reader hears the result once all files are through.
	const counts = $derived(uploads.counts);
	const line = $derived(
		[
			m.upload_summary_uploaded({ count: counts.uploaded }),
			counts.duplicates === 1
				? m.upload_summary_duplicate()
				: counts.duplicates > 1 && m.upload_summary_duplicates({ count: counts.duplicates }),
			counts.skipped > 0 && m.upload_summary_skipped({ count: counts.skipped }),
			counts.failed > 0 && m.upload_summary_failed({ count: counts.failed })
		]
			.filter(Boolean)
			.join(', ')
	);
	const notable = $derived(
		uploads.items.filter((item) => ['duplicate', 'skipped', 'failed'].includes(item.state))
	);
	const REASONS: Record<SkipReason, () => string> = {
		type: m.upload_skipped_type,
		hidden: m.upload_skipped_hidden,
		too_large: m.upload_skipped_too_large,
		unreadable: m.upload_skipped_unreadable
	};
</script>

{#if uploads.items.length > 0}
	<Card.Root as="section" size="row" aria-label={m.upload_summary_label()}>
		<div class="flex items-start gap-3">
			<Upload class="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
			<div class="flex min-w-0 flex-1 flex-col gap-2">
				<p class="font-medium">{line}</p>
				<!-- Said once, when every file is through, not for each one. -->
				<p class="sr-only" aria-live="polite">{uploads.active ? '' : line}</p>
				{#if uploads.active}
					<Progress value={counts.done} max={counts.total} aria-label={m.upload_title()} />
					<p class="text-sm text-muted-foreground">
						{m.upload_running({ done: counts.done, total: counts.total })}
					</p>
				{/if}
			</div>
			<Button
				variant="ghost"
				size="icon"
				class="-mt-1.5 -mr-1.5 size-11 sm:size-9"
				aria-label={m.upload_dismiss()}
				disabled={uploads.active}
				onclick={() => uploads.dismiss()}
			>
				<X aria-hidden="true" />
			</Button>
		</div>
		{#if notable.length > 0}
			<ul class="mt-3 flex max-h-48 flex-col gap-1.5 overflow-auto border-t pt-3 text-sm">
				{#each notable as item (item.key)}
					<li class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
						<span class="min-w-0 truncate font-medium" title={item.name}>{item.name}</span>
						{#if item.state === 'duplicate'}
							<span class="flex items-center gap-1 text-muted-foreground">
								<Copy class="size-3.5 shrink-0" aria-hidden="true" />
								{m.upload_duplicate()}
							</span>
							{#if item.documentId}
								<a
									href="{BASE}/documents/{item.documentId}"
									class="text-brand underline-offset-4 hover:underline"
								>
									{m.upload_existing()}
								</a>
							{:else}
								<span class="text-muted-foreground">{m.upload_duplicate_unseen()}</span>
							{/if}
						{:else if item.state === 'skipped' && item.reason}
							<span class="text-muted-foreground">{REASONS[item.reason]()}</span>
						{:else}
							<span class="flex items-center gap-1 text-destructive">
								<CircleAlert class="size-3.5 shrink-0" aria-hidden="true" />
								{item.message}
							</span>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</Card.Root>
{/if}
