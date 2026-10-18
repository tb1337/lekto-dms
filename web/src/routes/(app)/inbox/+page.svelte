<script lang="ts">
	import CheckCheck from '@lucide/svelte/icons/check-check';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import InboxRow from '#lib/components/InboxRow.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { inbox, type InboxSummary } from '#lib/inbox.svelte.ts';
	import { inboxTabHref, inboxTabOf, type InboxItem, type InboxTab } from '#lib/inbox-view.ts';
	import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';
	import { PagedList } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// The inbox: everything new until a person saw it or decided, by tab (`?tab=`; none: all
	// that is open). Documents in processing with their progress, yellow and red ones to decide,
	// new ones (green by themselves) calmly with "seen", and what left in the last 14 days.
	// Live: events refresh the list (progress too) and the counts.
	const tab = $derived(inboxTabOf(page.url.searchParams));
	let lookup = $state<Lookup | null>(null);
	// The document whose row runs an action.
	let busy = $state<string | null>(null);
	let askAll = $state(false);

	const list = new PagedList<InboxItem>(async (cursor) => {
		const data = await unwrap(
			api.GET('/api/v1/inbox', {
				params: {
					query: {
						tab: tab ?? undefined,
						cursor: (cursor as string | null) ?? undefined,
						all_users: scope.query
					}
				}
			})
		);
		return { items: data.items, next: data.next_cursor };
	});

	$effect(() => {
		void tab;
		void scope.allUsers;
		void events.generation;
		void list.reload();
	});

	onMount(() => {
		loadLookup().then(
			(value) => (lookup = value),
			() => {}
		);
		let timer: ReturnType<typeof setTimeout> | undefined;
		// Events are thin: fetch the list again, at most once in a while.
		const stop = events.subscribe(() => {
			clearTimeout(timer);
			timer = setTimeout(() => void list.refresh(), 400);
		});
		return () => {
			clearTimeout(timer);
			stop();
		};
	});

	async function changed() {
		await Promise.all([list.refresh(), inbox.refresh()]);
	}

	async function mark(id: string, seen: boolean) {
		busy = id;
		try {
			const params = { params: { path: { id } } };
			await unwrap(
				seen
					? api.PUT('/api/v1/documents/{id}/seen', params)
					: api.DELETE('/api/v1/documents/{id}/seen', params)
			);
			toast.success(seen ? m.inbox_seen_done() : m.inbox_unseen_done());
			await changed();
		} catch (error) {
			reportError(error);
		} finally {
			busy = null;
		}
	}

	async function markAll() {
		const { marked } = await unwrap(
			api.POST('/api/v1/inbox/seen', { params: { query: { all_users: scope.query } } })
		);
		toast.success(m.inbox_all_seen_done({ count: marked }));
		await changed();
	}

	const TABS: { tab: InboxTab | null; label: () => string; count: (s: InboxSummary) => number }[] =
		[
			{ tab: null, label: m.inbox_all, count: (summary) => summary.open },
			{ tab: 'new', label: m.inbox_new, count: (summary) => summary.new },
			{ tab: 'review', label: m.inbox_review, count: (summary) => summary.review },
			{ tab: 'intervene', label: m.inbox_intervene, count: (summary) => summary.intervene },
			{ tab: 'processing', label: m.inbox_processing, count: (summary) => summary.processing },
			{ tab: 'done', label: m.inbox_done, count: (summary) => summary.done }
		];
	const EMPTY: Record<InboxTab | 'all', () => string> = {
		all: m.inbox_empty,
		new: m.inbox_empty_new,
		review: m.inbox_empty_review,
		intervene: m.inbox_empty_intervene,
		processing: m.inbox_empty_processing,
		done: m.inbox_empty_done
	};
	const fresh = $derived(inbox.summary?.new ?? 0);
</script>

<svelte:head><title>{m.nav_inbox()} · p:api:q</title></svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_inbox()}</h1>
	</div>

	<div class="flex flex-wrap items-center justify-between gap-3">
		<!-- On a phone the tabs scroll sideways in their own row. -->
		<nav
			aria-label={m.inbox_tabs_label()}
			class="flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-secondary p-1"
		>
			{#each TABS as entry (entry.tab)}
				{@const count = inbox.summary ? entry.count(inbox.summary) : 0}
				<a
					href={inboxTabHref(entry.tab)}
					aria-current={tab === entry.tab ? 'page' : undefined}
					class={cn(
						'inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-sm whitespace-nowrap transition-colors sm:h-[34px] sm:px-4',
						tab === entry.tab
							? 'bg-card font-medium text-foreground shadow-sm'
							: 'text-muted-foreground hover:text-foreground'
					)}
				>
					{entry.label()}
					{#if count > 0}
						<span class="text-xs font-normal text-muted-foreground tabular-nums">{count}</span>
					{/if}
				</a>
			{/each}
		</nav>
		{#if (tab === null || tab === 'new') && fresh > 0}
			<Button variant="ghost" class="h-11 sm:h-9" onclick={() => (askAll = true)}>
				<CheckCheck aria-hidden="true" />
				{m.inbox_all_seen()}
			</Button>
		{/if}
	</div>

	{#if list.error}
		<div class="flex flex-col items-start gap-3" role="alert">
			<p class="text-destructive">{describeError(list.error)}</p>
			<Button variant="outline" onclick={() => list.reload()}>{m.retry()}</Button>
		</div>
	{:else if list.empty}
		<p
			class="rounded-2xl border border-dashed bg-card px-6 py-16 text-center text-muted-foreground"
		>
			{EMPTY[tab ?? 'all']()}
		</p>
	{:else}
		<ul class="flex flex-col gap-2" aria-busy={list.loading}>
			{#each list.items as item (item.document.id)}
				<li>
					<InboxRow
						{item}
						{lookup}
						busy={busy === item.document.id}
						onseen={(id) => mark(id, true)}
						onunseen={(id) => mark(id, false)}
					/>
				</li>
			{/each}
		</ul>
		{#if list.loading && !list.loaded}
			<p class="text-muted-foreground">{m.loading()}</p>
		{/if}
		{#if list.hasMore}
			<div class="flex justify-center">
				<Button variant="outline" disabled={list.loading} onclick={() => list.more()}>
					{m.load_more()}
				</Button>
			</div>
		{/if}
	{/if}
</div>

<ConfirmDialog
	bind:open={askAll}
	title={m.inbox_all_seen_title()}
	description={fresh === 1 ? m.inbox_all_seen_text_one() : m.inbox_all_seen_text({ count: fresh })}
	confirmLabel={m.inbox_all_seen_confirm()}
	destructive={false}
	onconfirm={markAll}
/>
