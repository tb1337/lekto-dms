<script lang="ts" module>
	export interface Reference {
		id: string;
		title: string;
		/** Tells documents apart whose titles a pattern made alike ("2026/04"). */
		filename: string;
	}
</script>

<script lang="ts">
	import ChevronsUpDown from '@lucide/svelte/icons/chevrons-up-down';
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as Command from '#lib/components/ui/command/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The document a template is shown with. At first the newest of the type (a title pattern's),
	// else the newest the user may read; typing searches the words of all documents (without a
	// search index: the titles of the newest).
	let {
		value = $bindable(null),
		documentType = undefined,
		preselect = true,
		label = undefined,
		exclude = undefined
	}: {
		value?: Reference | null;
		documentType?: string | null;
		/** Whether the newest document is chosen at first (a template's example); without, the
		 * newest are only fetched once the list opens. */
		preselect?: boolean;
		/** What the trigger says (and is named) while nothing is chosen. */
		label?: string;
		/** A document not to offer (the one being related). */
		exclude?: string;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let recent = $state<Reference[]>([]);
	let found = $state<Reference[] | null>(null);

	const short = (item: { id: string; title: string; original_filename: string }): Reference => ({
		id: item.id,
		title: item.title,
		filename: item.original_filename
	});

	$effect(() => {
		const kind = documentType ?? null;
		if (!preselect && !open) return;
		let current = true;
		const newest = async (type: string | null) =>
			(
				await unwrap(
					api.GET('/api/v1/documents', {
						params: { query: { limit: 50, document_type_id: type ? [type] : undefined } }
					})
				)
			).items.map(short);
		void (async () => {
			try {
				let items = kind ? await newest(kind) : [];
				if (items.length === 0) items = await newest(null);
				if (!current) return;
				recent = items;
				if (preselect && untrack(() => value) === null) value = items[0] ?? null;
			} catch {
				if (current) recent = [];
			}
		})();
		return () => {
			current = false;
		};
	});

	$effect(() => {
		const text = query.trim();
		found = null;
		if (!text) return;
		let current = true;
		const timer = setTimeout(() => {
			void unwrap(
				api.POST('/api/v1/documents/search', {
					params: { query: { limit: 20, semantic_ratio: 0 } },
					body: { q: text }
				})
			).then(
				(page) => {
					if (current) found = page.items.map((item) => short(item.document));
				},
				() => {
					const wanted = text.toLocaleLowerCase();
					if (current) {
						found = untrack(() => recent).filter((item) =>
							item.title.toLocaleLowerCase().includes(wanted)
						);
					}
				}
			);
		}, 250);
		return () => {
			current = false;
			clearTimeout(timer);
		};
	});

	const shown = $derived((found ?? recent).filter((item) => item.id !== exclude));

	function choose(item: Reference) {
		value = item;
		open = false;
		query = '';
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class={cn(buttonVariants({ variant: 'outline' }), 'w-full justify-between font-normal')}
		aria-label={value ? m.template_reference_choose() : (label ?? m.template_reference_choose())}
	>
		<span class="truncate">{value?.title ?? label ?? m.template_reference_none()}</span>
		<ChevronsUpDown class="opacity-50" aria-hidden="true" />
	</Popover.Trigger>
	<Popover.Content class="w-(--bits-popover-anchor-width) min-w-64 p-0" align="start">
		<Command.Root shouldFilter={false}>
			<Command.Input
				bind:value={query}
				placeholder={m.template_reference_search()}
				aria-label={m.template_reference_search()}
			/>
			<Command.List>
				<Command.Empty class="py-4 text-center text-sm text-muted-foreground">
					{m.template_reference_empty()}
				</Command.Empty>
				{#each shown as item (item.id)}
					<Command.Item
						value={item.id}
						onSelect={() => choose(item)}
						class="flex-col items-start gap-0"
					>
						<span class="max-w-full truncate">{item.title}</span>
						<span class="max-w-full truncate text-xs text-muted-foreground">{item.filename}</span>
					</Command.Item>
				{/each}
			</Command.List>
		</Command.Root>
	</Popover.Content>
</Popover.Root>
