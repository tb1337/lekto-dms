<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { SvelteSet } from 'svelte/reactivity';
	import { toast } from 'svelte-sonner';
	import { BASE } from '#lib/base.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import DocumentCount from '#lib/components/DocumentCount.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { type Item, KINDS, type TagKind } from '#lib/masterdata-api.ts';
	import type { Tag } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';
	import { visibleRows } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The tags of one scope as a tree, each as its chip (icon and colour, a topic square, a
	// group outlined): expand and collapse, how many documents each stands for (with the tags
	// below it), add, change and delete.
	let { kind }: { kind: TagKind } = $props();
	const ops = $derived(KINDS[kind]);
	const DELETE_CONFIRM: Record<TagKind, () => string> = {
		tags: m.tag_delete_confirm,
		'contact-groups': m.contact_group_delete_confirm,
		'type-groups': m.type_group_delete_confirm,
		topics: m.topic_delete_confirm
	};

	let items = $state<Tag[] | null>(null);
	let problem = $state<string | null>(null);
	let removing = $state<Item | null>(null);
	const collapsed = new SvelteSet<string>();
	// Each level further in (less so on a phone); the fifth, the deepest, at most.
	const INDENT = ['pl-2', 'pl-6 sm:pl-9', 'pl-10 sm:pl-16', 'pl-14 sm:pl-23', 'pl-18 sm:pl-30'];
	const rows = $derived(items ? visibleRows(items, collapsed) : []);

	async function load() {
		try {
			items = (await ops.list({ counts: true, allUsers: scope.allUsers })) as Tag[];
			problem = null;
		} catch (error) {
			problem = describeError(error);
		}
	}

	// Again after a dialog saved (wherever it was opened), and with another scope.
	$effect(() => {
		void masterDataDialogs.changed;
		void scope.allUsers;
		void load();
	});

	/** How a tag is set and whether documents show it, where it is not the default. */
	function marks(tag: Tag): string {
		return [
			(tag.scope === 'document' || tag.scope === 'topic') && tag.assignment === 'manual'
				? m.tag_assignment_manual()
				: null,
			tag.shown ? null : m.tag_hidden()
		]
			.filter(Boolean)
			.join(' · ');
	}

	function filterHref(tag: Tag): string {
		return `${BASE}/documents?${ops.filter}=${tag.id}`;
	}

	function toggle(id: string) {
		if (collapsed.has(id)) collapsed.delete(id);
		else collapsed.add(id);
	}

	async function remove() {
		if (!removing) return;
		await ops.remove(removing.id);
		toast.success(m.master_deleted());
		await load();
	}
</script>

<div class="flex flex-col gap-4">
	<div>
		<Button onclick={() => masterDataDialogs.open(kind)}>
			<Plus aria-hidden="true" />
			{ops.add()}
		</Button>
	</div>
	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !items}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else if items.length === 0}
		<p
			class="rounded-2xl border border-dashed bg-card px-6 py-10 text-center text-muted-foreground"
		>
			{m.master_none()}
		</p>
	{:else}
		<ul class="flex flex-col gap-2" aria-label={ops.title()}>
			{#each rows as { tag, depth, hasChildren } (tag.id)}
				<li
					class={cn(
						'flex items-center gap-2 rounded-2xl border bg-card py-2 pr-2',
						INDENT[Math.min(depth, INDENT.length - 1)]
					)}
				>
					{#if hasChildren}
						<Button
							variant="ghost"
							size="icon"
							class="size-8 shrink-0"
							aria-expanded={!collapsed.has(tag.id)}
							aria-label={collapsed.has(tag.id)
								? m.tree_expand({ name: tag.name })
								: m.tree_collapse({ name: tag.name })}
							onclick={() => toggle(tag.id)}
						>
							{#if collapsed.has(tag.id)}
								<ChevronRight aria-hidden="true" />
							{:else}
								<ChevronDown aria-hidden="true" />
							{/if}
						</Button>
					{:else}
						<span class="size-8 shrink-0" aria-hidden="true"></span>
					{/if}
					<div class="flex min-w-0 flex-1 flex-col items-start">
						<TagChip
							tag={{ ...tag, path: [tag.name] }}
							topic={tag.scope === 'topic'}
							group={tag.scope === 'contact' || tag.scope === 'document_type'}
						/>
						{#if marks(tag)}
							<span class="max-w-full truncate text-sm text-muted-foreground">{marks(tag)}</span>
						{/if}
						<!-- On a phone the count goes under the name: the row is too narrow for both. -->
						<span class="-ml-2.5 sm:hidden">
							<DocumentCount count={tag.document_count} href={filterHref(tag)} />
						</span>
					</div>
					<span class="hidden sm:inline-flex">
						<DocumentCount count={tag.document_count} href={filterHref(tag)} />
					</span>
					<Button
						variant="ghost"
						size="icon"
						class="shrink-0"
						aria-label={m.master_edit({ name: tag.name })}
						onclick={() => masterDataDialogs.open(kind, tag)}
					>
						<Pencil aria-hidden="true" />
					</Button>
					<Button
						variant="ghost"
						size="icon"
						class="shrink-0"
						aria-label={m.master_delete({ name: tag.name })}
						onclick={() => (removing = tag)}
					>
						<Trash2 aria-hidden="true" />
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<ConfirmDialog
	bind:open={() => removing !== null, (open) => !open && (removing = null)}
	title={m.master_delete({ name: removing?.name ?? '' })}
	description={DELETE_CONFIRM[kind]()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
