<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import OpenIdentifierDialog from '#lib/components/OpenIdentifierDialog.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { ChoiceBox } from '#lib/components/ui/choice/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { shown } from '#lib/facts.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { type IdentifierKind, kindLabel } from '#lib/identifiers.ts';
	import {
		confirmable,
		decide,
		documentsHref,
		type OpenAction,
		type OpenDecision,
		type OpenIdentifier,
		type OpenPage,
		openKey
	} from '#lib/open-identifiers.ts';
	import { Pager } from '#lib/paging.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { reasonText } from '#lib/reasons.ts';
	import { cn } from '#lib/utils.ts';

	// The tab "Kennungen" of the master data (Tobi, 27.10.2026): the identifiers no person has
	// confirmed, learned at a contact or standing in confirmed documents at no contact, the most
	// documents first. Narrowed by where they are open, their kind and the page's search. Rows
	// are chosen with their box for "Übernehmen" and "Verwerfen" on many at once (the selection
	// bar above the list, at the bottom on a phone); the value opens one with where it stands.
	let { query = '' }: { query?: string } = $props();

	type Source = '' | OpenIdentifier['source'];
	const SIZE = 50;

	let source = $state<Source>('');
	let kind = $state('');
	let counts = $state<OpenPage['counts']>({ learned: 0, unknown: 0 });
	let kinds = $state<OpenPage['kinds']>({});
	let chosen = $state<Record<string, OpenIdentifier>>({});
	let busy = $state(false);
	let opened = $state<OpenIdentifier | null>(null);
	let dialog = $state(false);

	const list = new Pager<OpenIdentifier>(async (offset, limit) => {
		const found = await unwrap(
			api.GET('/api/v1/identifiers/open', {
				params: {
					query: {
						source: source || undefined,
						kind: (kind || undefined) as IdentifierKind | undefined,
						q: query.trim() || undefined,
						offset,
						limit
					}
				}
			})
		);
		counts = found.counts;
		kinds = found.kinds;
		return { items: found.items, total: found.total };
	}, SIZE);

	// Again for other words, a moment after the last key.
	let typed: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		void query;
		clearTimeout(typed);
		typed = setTimeout(() => void list.reload(), list.loaded ? 250 : 0);
		return () => clearTimeout(typed);
	});

	const selection = $derived(Object.values(chosen));
	const skipped = $derived(selection.filter((item) => !confirmable(item)).length);
	const pageChosen = $derived(
		list.items.length > 0 && list.items.every((item) => openKey(item) in chosen)
	);
	const anyKinds = $derived(Object.keys(kinds).length > 0);

	function show(next: string) {
		source = next as Source;
		void list.reload();
	}

	function narrow(next: string) {
		kind = next;
		void list.reload();
	}

	function toggle(item: OpenIdentifier, on: boolean) {
		const key = openKey(item);
		const next = { ...chosen };
		if (on) next[key] = item;
		else delete next[key];
		chosen = next;
	}

	function togglePage(on: boolean) {
		const next = { ...chosen };
		for (const item of list.items) {
			if (on) next[openKey(item)] = item;
			else delete next[openKey(item)];
		}
		chosen = next;
	}

	async function decideChosen(action: OpenAction) {
		if (busy) return;
		const items = action === 'confirm' ? selection.filter(confirmable) : selection;
		if (items.length === 0) return;
		busy = true;
		try {
			const decisions: OpenDecision[] = items.map((item) => ({
				kind: item.kind,
				value: item.value,
				action
			}));
			const outcomes = await decide(decisions);
			const done = outcomes.filter((outcome) => outcome.done).length;
			const failed = outcomes.filter((outcome) => !outcome.done);
			if (done > 0) {
				toast.success(
					action === 'confirm'
						? m.open_confirmed({ count: formatNumber(done) })
						: m.open_rejected({ count: formatNumber(done) })
				);
			}
			const first = failed[0]?.reason;
			if (first) {
				toast.error(
					m.open_failed({ count: formatNumber(failed.length), reason: reasonText(first) })
				);
			}
			chosen = {};
			await list.refresh();
		} catch (error) {
			toast.error(describeError(error));
		} finally {
			busy = false;
		}
	}

	function openItem(item: OpenIdentifier) {
		opened = item;
		dialog = true;
	}

	function decided(action: OpenAction) {
		toast.success(
			action === 'confirm'
				? m.open_confirmed({ count: formatNumber(1) })
				: m.open_rejected({ count: formatNumber(1) })
		);
		if (opened) toggle(opened, false);
		void list.refresh();
	}

	function documentsText(count: number): string {
		return count === 1 ? m.open_documents_one() : m.open_documents({ count: formatNumber(count) });
	}

	function contactText(item: OpenIdentifier): string {
		return item.contacts.length === 1
			? item.contacts[0].name
			: m.open_contacts_many({ count: formatNumber(item.contacts.length) });
	}
</script>

{#snippet sourceBadge(item: OpenIdentifier)}
	<Badge variant={item.source === 'learned' ? 'note' : 'muted'}>
		{item.source === 'learned' ? m.open_learned() : m.open_unknown()}
	</Badge>
{/snippet}

{#snippet bar()}
	<div
		class={cn(
			'flex flex-wrap items-center gap-x-3 gap-y-2',
			phone.current
				? 'sticky bottom-0 z-10 -mx-4 border-t bg-card px-4 pt-3 pb-4'
				: cn('rounded-2xl border bg-panel py-2 pr-2 pl-4', 'sticky top-2 z-10')
		)}
		role="region"
		aria-label={m.open_selected({ count: formatNumber(selection.length) })}
	>
		<span class="font-medium">{m.open_selected({ count: formatNumber(selection.length) })}</span>
		{#if skipped > 0}
			<span class="text-meta text-muted-foreground max-sm:order-last max-sm:basis-full sm:flex-1">
				{skipped === 1 ? m.open_skipped_one() : m.open_skipped({ count: formatNumber(skipped) })}
			</span>
		{:else}
			<span class="flex-1"></span>
		{/if}
		<Button variant="ghost" size="sm" disabled={busy} onclick={() => (chosen = {})}>
			{m.open_selection_clear()}
		</Button>
		<div class={cn('flex gap-2', phone.current && 'grid flex-1 basis-full grid-cols-2')}>
			<Button variant="outline" size="sm" disabled={busy} onclick={() => decideChosen('reject')}>
				{m.open_reject()}
			</Button>
			<Button
				size="sm"
				disabled={busy || selection.length === skipped}
				onclick={() => decideChosen('confirm')}
			>
				{m.open_confirm()}
			</Button>
		</div>
	</div>
{/snippet}

<div class="flex flex-col gap-3">
	<p class="text-meta text-muted-foreground">{m.open_hint()}</p>
	<div class="flex flex-wrap items-center justify-between gap-3">
		<Segmented
			label={m.open_source()}
			value={source}
			onchange={show}
			options={[
				{
					value: '',
					label: m.open_all(),
					count: formatNumber(counts.learned + counts.unknown)
				},
				{ value: 'learned', label: m.open_learned(), count: formatNumber(counts.learned) },
				{ value: 'unknown', label: m.open_unknown(), count: formatNumber(counts.unknown) }
			]}
		/>
		{#if anyKinds || kind}
			<Select
				aria-label={m.open_kind()}
				class="w-auto min-w-48"
				value={kind}
				onchange={narrow}
				options={[
					{ value: '', label: m.open_kind_any() },
					...Object.entries(kinds).map(([value, count]) => ({
						value,
						label: `${kindLabel(value as IdentifierKind)} (${formatNumber(count ?? 0)})`
					}))
				]}
			/>
		{/if}
	</div>

	{#if selection.length > 0 && !phone.current}{@render bar()}{/if}

	{#if list.error && !list.loaded}
		<LoadProblem problem={describeError(list.error)} onretry={() => list.reload()} />
	{:else if !list.loaded}
		<Loading />
	{:else if list.empty}
		<EmptyNote compact>
			{counts.learned + counts.unknown === 0 && !query.trim() ? m.open_none() : m.open_none_found()}
		</EmptyNote>
	{:else}
		<Card.Root size="flush" class="overflow-hidden">
			<div
				class="flex items-center gap-3 border-b py-2 pr-4 pl-4 text-xs font-medium text-muted-foreground"
			>
				<ChoiceBox
					checked={pageChosen}
					aria-label={m.open_select_all()}
					onchange={(event) => togglePage(event.currentTarget.checked)}
				/>
				{#if phone.current}
					<span>{m.open_select_all()}</span>
				{:else}
					<span
						class="grid flex-1 grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_6.5rem] gap-3"
					>
						<span>{m.open_column_identifier()}</span>
						<span>{m.open_column_contact()}</span>
						<span>{m.open_column_documents()}</span>
						<span>{m.open_source()}</span>
					</span>
				{/if}
			</div>
			<ul class="divide-y" aria-label={m.master_identifiers()}>
				{#each list.items as item (openKey(item))}
					{@const key = openKey(item)}
					{@const value = shown(item)}
					<li
						class={cn('flex min-h-14 gap-3 py-2.5 pr-4 pl-4', key in chosen && 'bg-panel')}
						data-row
					>
						<ChoiceBox
							class="mt-1 shrink-0"
							checked={key in chosen}
							aria-label={m.open_select({ value })}
							onchange={(event) => toggle(item, event.currentTarget.checked)}
						/>
						{#if phone.current}
							<div class="flex min-w-0 flex-1 flex-col gap-0.5">
								<div class="flex items-center justify-between gap-2">
									<span class="text-xs text-muted-foreground">{kindLabel(item.kind)}</span>
									{@render sourceBadge(item)}
								</div>
								<Button
									variant="link"
									size="inline"
									class="h-auto justify-start p-0 text-left font-mono text-meta break-all whitespace-normal"
									aria-label={m.open_open({ value })}
									onclick={() => openItem(item)}>{value}</Button
								>
								<span class="text-meta text-muted-foreground">
									{contactText(item)} · {documentsText(item.documents)}
								</span>
							</div>
						{:else}
							<div
								class="grid flex-1 grid-cols-[minmax(0,2.2fr)_minmax(0,1.6fr)_minmax(0,1.2fr)_6.5rem] items-center gap-3"
							>
								<div class="flex min-w-0 flex-col">
									<span class="text-xs text-muted-foreground">{kindLabel(item.kind)}</span>
									<Button
										variant="link"
										size="inline"
										class="block h-auto max-w-full justify-start truncate p-0 text-left font-mono text-meta"
										aria-label={m.open_open({ value })}
										onclick={() => openItem(item)}>{value}</Button
									>
								</div>
								<div class="flex min-w-0 items-center gap-2">
									{#if item.contacts.length === 1}
										<ContactAvatar contact={{ name: item.contacts[0].name, logo: null }} />
									{/if}
									<span
										class={cn(
											'truncate text-sm',
											item.contacts.length > 1 && 'text-muted-foreground'
										)}>{contactText(item)}</span
									>
								</div>
								<div class="flex flex-col">
									<a
										class="text-sm text-brand tabular-nums hover:underline"
										href={documentsHref(item)}>{documentsText(item.documents)}</a
									>
									{#if item.last}
										<span class="text-xs text-muted-foreground">
											{m.open_last({ date: formatDate(item.last) })}
										</span>
									{/if}
								</div>
								<span>{@render sourceBadge(item)}</span>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		</Card.Root>
		<Pagination
			page={list.page}
			total={list.total}
			size={list.size}
			onchange={(page) => list.go(page)}
		/>
	{/if}

	{#if selection.length > 0 && phone.current}{@render bar()}{/if}
</div>

<OpenIdentifierDialog bind:open={dialog} item={opened} ondecided={decided} />
