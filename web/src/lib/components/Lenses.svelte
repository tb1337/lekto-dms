<script lang="ts">
	import SteadyText from '#lib/components/SteadyText.svelte';
	import Bookmark from '@lucide/svelte/icons/bookmark';
	import Files from '@lucide/svelte/icons/files';
	import Plus from '@lucide/svelte/icons/plus';
	import type { Lens } from '#lib/lenses.ts';
	import { m } from '#lib/paraglide/messages.js';
	import * as Card from '#lib/components/ui/card/index.ts';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import Chip from '#lib/components/Chip.svelte';
	import { formatNumber } from '#lib/i18n.ts';

	// The user's lenses as links: all documents first, then each lens, each with how many
	// documents it shows (`counts`, Tobi 28.10.2026); `onadd` offers a new one from the filters. Beside the list a card (`list`), on a phone a row of chips (`chips`).
	let {
		lenses,
		active,
		href,
		allHref,
		changed = false,
		onadd,
		counts = {},
		variant = 'list'
	}: {
		lenses: readonly Lens[];
		/** The open lens; null: all documents. */
		active: string | null;
		href: (lens: Lens) => string;
		allHref: string;
		/** The open lens differs from what the page shows. */
		changed?: boolean;
		onadd?: () => void;
		/** How many documents each shows, by lens id (`all` for all documents); none: unknown. */
		counts?: Readonly<Record<string, number>>;
		variant?: 'list' | 'chips';
	} = $props();

	const id = $props.id();
	const entries = $derived([
		{ id: null, name: m.lens_all(), href: allHref },
		...lenses.map((lens) => ({ id: lens.id, name: lens.name, href: href(lens) }))
	]);
</script>

{#if variant === 'list'}
	<Card.Root as="section" size="flush" class="px-2 pb-2" aria-labelledby="{id}-title">
		<div class="flex h-10 items-center gap-2 px-1">
			<Eyebrow as="h2" id="{id}-title" class="m-0 flex-1 tracking-wider">
				{m.lens_title()}
			</Eyebrow>
			{#if onadd}
				<IconButton
					label={m.lens_new()}
					variant="outline"
					size="sm"
					class="text-brand"
					onclick={onadd}
				>
					<Plus aria-hidden="true" />
				</IconButton>
			{/if}
		</div>
		<ul class="flex flex-col">
			{#each entries as entry (entry.id)}
				{@const current = entry.id === active}
				<li>
					<a
						href={entry.href}
						aria-current={current ? 'page' : undefined}
						class={[
							'flex h-9 items-center gap-2.5 rounded-lg px-2 text-sm hover:bg-secondary',
							current && 'bg-secondary font-medium'
						]}
					>
						{#if entry.id === null}
							<Files
								class={['size-4 shrink-0', current ? 'text-brand' : 'text-muted-foreground']}
								aria-hidden="true"
							/>
						{:else}
							<Bookmark
								class={['size-4 shrink-0', current ? 'text-brand' : 'text-muted-foreground']}
								aria-hidden="true"
							/>
						{/if}
						<span class="min-w-0 flex-1 truncate">{entry.name}</span>
						{#if counts[entry.id ?? 'all'] !== undefined}
							<span class="text-xs text-muted-foreground tabular-nums">
								{formatNumber(counts[entry.id ?? 'all'])}
							</span>
						{/if}
						{#if current && changed && entry.id !== null}
							<span
								class="size-2 shrink-0 rounded-full bg-lane-yellow-foreground"
								title={m.lens_changed_mark()}
							></span>
							<span class="sr-only">{m.lens_changed_mark()}</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</Card.Root>
{:else}
	<nav class="-mx-4 -my-1.5 flex gap-1.5 overflow-x-auto px-4 py-1.5" aria-label={m.lens_title()}>
		{#each entries as entry (entry.id)}
			{@const current = entry.id === active}
			<a
				href={entry.href}
				aria-current={current ? 'page' : undefined}
				class={[
					// Chips as everywhere (web/DESIGN.md): the chosen one in the selected look.
					'relative inline-flex h-8 shrink-0 items-center rounded-full px-3 text-sm whitespace-nowrap after:absolute after:inset-x-0 after:-inset-y-1.5',
					current
						? 'bg-panel font-medium text-brand ring-1 ring-primary/30 ring-inset'
						: 'border bg-card hover:bg-secondary'
				]}
			>
				<SteadyText text={entry.name} />
			</a>
		{/each}
		{#if onadd}
			<Chip variant="add" class="shrink-0" onclick={onadd}>
				{#snippet icon()}<Plus class="size-4 shrink-0" aria-hidden="true" />{/snippet}
				{m.lens_new()}
			</Chip>
		{/if}
	</nav>
{/if}
