<script lang="ts">
	import Bookmark from '@lucide/svelte/icons/bookmark';
	import Files from '@lucide/svelte/icons/files';
	import Plus from '@lucide/svelte/icons/plus';
	import type { Lens } from '#lib/lenses.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The user's lenses as links: all documents first, then each lens; `onadd` offers a new one
	// from the filters. Beside the list a card (`list`), on a phone a row of chips (`chips`).
	let {
		lenses,
		active,
		href,
		allHref,
		changed = false,
		onadd,
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
		variant?: 'list' | 'chips';
	} = $props();

	const id = $props.id();
	const entries = $derived([
		{ id: null, name: m.lens_all(), href: allHref },
		...lenses.map((lens) => ({ id: lens.id, name: lens.name, href: href(lens) }))
	]);
</script>

{#if variant === 'list'}
	<section class="rounded-2xl border bg-card px-2 pb-2" aria-labelledby="{id}-title">
		<div class="flex h-10 items-center gap-2 px-1">
			<h3
				id="{id}-title"
				class="m-0 flex-1 text-xs font-semibold tracking-wider text-muted-foreground uppercase"
			>
				{m.lens_title()}
			</h3>
			{#if onadd}
				<button
					type="button"
					class="grid size-7 place-items-center rounded-full border bg-background text-brand hover:bg-secondary"
					aria-label={m.lens_new()}
					title={m.lens_new()}
					onclick={onadd}
				>
					<Plus class="size-3.5" aria-hidden="true" />
				</button>
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
	</section>
{:else}
	<nav class="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1" aria-label={m.lens_title()}>
		{#each entries as entry (entry.id)}
			{@const current = entry.id === active}
			<a
				href={entry.href}
				aria-current={current ? 'page' : undefined}
				class={[
					'inline-flex h-8 shrink-0 items-center rounded-full px-3 text-sm whitespace-nowrap',
					current
						? 'bg-primary font-semibold text-primary-foreground'
						: 'border bg-card hover:bg-secondary'
				]}
			>
				{entry.name}
			</a>
		{/each}
		{#if onadd}
			<button
				type="button"
				class="grid size-8 shrink-0 place-items-center rounded-full border border-dashed text-brand"
				aria-label={m.lens_new()}
				onclick={onadd}
			>
				<Plus class="size-3.5" aria-hidden="true" />
			</button>
		{/if}
	</nav>
{/if}
