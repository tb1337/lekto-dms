<script lang="ts">
	import CheckCheck from '@lucide/svelte/icons/check-check';
	import Upload from '@lucide/svelte/icons/upload';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { page } from '$app/state';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { ApiError } from '#lib/api/problem.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import InboxRow from '#lib/components/InboxRow.svelte';
	import UploadDialog from '#lib/components/UploadDialog.svelte';
	import UploadSummary from '#lib/components/UploadSummary.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError, reportError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { inbox, type InboxSummary } from '#lib/inbox.svelte.ts';
	import { inboxTabHref, inboxTabOf, type InboxItem, type InboxTab } from '#lib/inbox-view.ts';
	import { readDrop } from '#lib/intake.ts';
	import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';
	import { PagedList } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { scope } from '#lib/scope.svelte.ts';
	import { uploads } from '#lib/upload.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// The inbox, the way in: documents come here by the upload button (with the dialog) or by
	// dropping files and folders on the page (at once into the default space; not on a phone),
	// and everything new stands here until a person saw it or decided, by tab (`?tab=`; none:
	// all that is open). Documents in processing with their progress, yellow and red ones to
	// decide, new ones (green by themselves) calmly with "seen", and what left in the last 14
	// days. Live: events refresh the list (progress too) and the counts.
	const tab = $derived(inboxTabOf(page.url.searchParams));
	let lookup = $state<Lookup | null>(null);
	// The document whose row runs an action.
	let busy = $state<string | null>(null);
	let askAll = $state(false);
	let uploadOpen = $state(false);
	let tabsNav = $state<HTMLElement | null>(null);
	let dragging = $state(false);
	// Dropping on the page: not on a phone, and not while the dialog takes drops itself.
	const droppable = $derived(!phone.current && !uploadOpen);

	$effect(() => {
		if (!droppable) dragging = false;
	});

	// Where the tabs scroll sideways (a phone), the current one stands in view, in their row
	// only: the page itself does not move. Again once the counts widen the tabs.
	$effect(() => {
		void tab;
		void inbox.summary;
		const current = tabsNav?.querySelector<HTMLElement>('[aria-current="page"]');
		if (!tabsNav || !current) return;
		const left = current.offsetLeft - (tabsNav.clientWidth - current.offsetWidth) / 2;
		tabsNav.scrollLeft = Math.max(0, left);
	});

	function carriesFiles(event: DragEvent): boolean {
		return [...(event.dataTransfer?.types ?? [])].includes('Files');
	}

	// While files are dragged over the page the overlay covers it; it alone sees them leave.
	function dragOver(event: DragEvent) {
		if (!carriesFiles(event)) return;
		// Never let the browser open a dropped file instead of the app.
		event.preventDefault();
		if (event.dataTransfer) event.dataTransfer.dropEffect = droppable ? 'copy' : 'none';
		if (droppable) dragging = true;
	}

	function drop(event: DragEvent) {
		if (!carriesFiles(event)) return;
		event.preventDefault();
		dragging = false;
		if (!droppable || !event.dataTransfer) return;
		readDrop(event.dataTransfer).then((intake) => uploads.add(intake), reportError);
	}

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

	// After seen or new again the list starts over: a document moved between the tabs, and
	// "done" (ordered by when a document left) answers 422 for a cursor no longer in it.
	async function changed() {
		await Promise.all([list.reload(), inbox.refresh()]);
	}

	async function more() {
		await list.more();
		if (list.error instanceof ApiError && list.error.status === 422) await list.reload();
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

<svelte:window ondragenter={dragOver} ondragover={dragOver} ondrop={drop} />

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex min-w-0 flex-col gap-1">
			<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_inbox()}</h1>
			<p class="text-sm text-muted-foreground max-sm:hidden">{m.upload_page_hint()}</p>
		</div>
		<Button class="h-11 sm:h-10" onclick={() => (uploadOpen = true)}>
			<Upload aria-hidden="true" />
			{m.upload_title()}
		</Button>
	</div>

	<UploadSummary />

	<div class="flex flex-wrap items-center justify-between gap-3">
		<!-- On a phone the tabs scroll sideways in their own row. -->
		<nav
			bind:this={tabsNav}
			aria-label={m.inbox_tabs_label()}
			class="relative flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-secondary p-1"
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
			<Button variant="outline" class="h-11 sm:h-9" onclick={() => list.reload()}>
				{m.retry()}
			</Button>
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
				<Button variant="outline" class="h-11 sm:h-9" disabled={list.loading} onclick={more}>
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

<UploadDialog bind:open={uploadOpen} spaces={lookup?.spaces ?? []} users={lookup?.users ?? []} />

{#if dragging}
	<div
		role="presentation"
		class="fixed inset-0 z-50 grid place-items-center bg-background/85 p-6 backdrop-blur-sm"
		ondragleave={() => (dragging = false)}
	>
		<div
			class="pointer-events-none flex flex-col items-center gap-3 rounded-3xl border-2 border-dashed border-primary bg-card px-12 py-16 text-center shadow-lg"
		>
			<Upload class="size-9 text-primary" aria-hidden="true" />
			<p class="text-xl font-semibold">{m.upload_drop_overlay()}</p>
			<p class="text-sm text-muted-foreground">{m.upload_drop_overlay_hint()}</p>
		</div>
	</div>
{/if}
