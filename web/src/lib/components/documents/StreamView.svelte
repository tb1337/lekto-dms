<script lang="ts">
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import CornerDownRight from '@lucide/svelte/icons/corner-down-right';
	import { tick } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { documentHref } from '#lib/candidates.ts';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { describeError } from '#lib/errors.ts';
	import type { apiQuery } from '#lib/filters.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { isoDayLocal } from '#lib/dates.ts';
	import { phone } from '#lib/phone.svelte.ts';
	import {
		axisOf,
		dayOf,
		inMonth,
		laneTitle,
		monthOf,
		openingMonth,
		type StreamDocument,
		type StreamLane,
		type StreamOut
	} from '#lib/stream.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { cardVariants } from '#lib/components/ui/card/index.ts';
	import Loading from '#lib/components/Loading.svelte';

	// The documents of the filters in lanes (#145): a series with its relation target at the
	// start and its expected document at the end, branches off it, chains, and the rest. On the
	// desktop the months run from left to right, opened at the newest end; on a phone each lane
	// runs down, newest first. Lanes beyond the limit come folded and open on demand. `version`
	// changes when documents change: the stream loads again.
	let {
		query,
		lookup,
		version = 0
	}: { query: ReturnType<typeof apiQuery>; lookup: Lookup | null; version?: number } = $props();

	let stream = $state<StreamOut | null>(null);
	let problem = $state<string | null>(null);
	let attempt = $state(0);
	let expanded = $state(false);
	let scroller = $state<HTMLDivElement | null>(null);

	$effect(() => {
		const asked = query;
		void attempt;
		void version;
		let current = true;
		void unwrap(api.GET('/api/v1/documents/stream', { params: { query: asked } })).then(
			(found) => {
				if (!current) return;
				stream = found;
				problem = null;
			},
			(error) => {
				if (current) problem = describeError(error);
			}
		);
		return () => {
			current = false;
		};
	});

	const axis = $derived(stream ? axisOf(stream) : []);

	// A new stream opens with the newest document's month (or today's) at the right edge, not
	// an expected date far ahead; folded lanes closed.
	$effect(() => {
		const month = stream ? openingMonth(stream, axis, isoDayLocal(new Date())) : null;
		expanded = false;
		void tick().then(() => {
			if (!scroller) return;
			const column = month ? scroller.querySelector<HTMLElement>(`[data-month="${month}"]`) : null;
			scroller.scrollLeft = column
				? column.getBoundingClientRect().right -
					scroller.getBoundingClientRect().left -
					scroller.clientWidth
				: scroller.scrollWidth;
		});
	});
	// The lane names, then one column per month (a narrow one per gap). The grid is at least
	// as wide as its columns, so that the sticky lane names stay while it scrolls; wider, the
	// months share the room.
	const columns = $derived(
		`13rem ${axis.map((column) => (column.kind === 'gap' ? '3rem' : 'minmax(7.5rem, 1fr)')).join(' ')}`
	);
	const minWidth = $derived(
		`calc(13rem + ${axis.filter((column) => column.kind === 'month').length} * 7.5rem + ${axis.filter((column) => column.kind === 'gap').length} * 3rem)`
	);
	const lanes = $derived(stream?.lanes ?? []);
	const folded = $derived(lanes.filter((lane) => lane.folded).length);
	const firstFolded = $derived(lanes.findIndex((lane) => lane.folded));

	function joined(lane: StreamLane): string | null {
		if (lane.parent === null || lane.parent === undefined) return null;
		const parent = lanes[lane.parent];
		const document = [
			...(parent?.documents ?? []),
			...(parent?.target ? [parent.target] : [])
		].find((item) => item.id === lane.joins);
		return document ? m.stream_joins({ title: document.title }) : null;
	}

	const monthLabel = (month: string) =>
		formatDate(`${month}-01`, { month: 'short', year: '2-digit' });
	const gapLabel = (months: number) => m.stream_gap({ count: formatNumber(months) });
	const short = (document: StreamDocument) =>
		formatDate(dayOf(document), { day: '2-digit', month: '2-digit' });
	/** Newest first, as on a phone: the expected one on top, the target at the bottom. */
	const newestFirst = (lane: StreamLane) => [...lane.documents].reverse();
	const shown = (lane: StreamLane) => expanded || !lane.folded;
</script>

{#snippet chip(document: StreamDocument, target = false)}
	<a
		href={documentHref(document.id)}
		class={[
			'flex min-w-0 flex-col rounded-lg border bg-card px-2 py-1 text-xs hover:bg-accent',
			target && 'border-brand'
		]}
		title={document.title}
	>
		<span class="truncate font-medium">{document.title}</span>
		<span class="text-muted-foreground"
			>{target ? `${m.stream_target()} · ` : ''}{short(document)}{document.lane === null
				? ` · ${m.inbox_processing()}`
				: ''}</span
		>
	</a>
{/snippet}

{#snippet expected(lane: StreamLane)}
	{#if lane.expected}
		<div
			class={[
				'flex items-center gap-1 rounded-lg border border-dashed px-2 py-1 text-xs',
				lane.expected.state === 'overdue'
					? 'border-destructive text-destructive'
					: 'text-muted-foreground'
			]}
		>
			<CalendarClock class="size-3.5 shrink-0" aria-hidden="true" />
			<span class="truncate"
				>{m.stream_expected({ date: formatDate(lane.expected.next_date) })}</span
			>
		</div>
	{/if}
{/snippet}

{#snippet toggle()}
	<button
		type="button"
		class="flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
		aria-expanded={expanded}
		onclick={() => (expanded = !expanded)}
	>
		{#if expanded}
			<ChevronUp class="size-4" aria-hidden="true" />
			{m.stream_fewer()}
		{:else}
			<ChevronDown class="size-4" aria-hidden="true" />
			{m.stream_more({ count: formatNumber(folded) })}
		{/if}
	</button>
{/snippet}

{#if problem}
	<LoadProblem {problem} onretry={() => attempt++} />
{:else if !stream}
	<Loading />
{:else if lanes.length === 0}
	<EmptyNote>{m.stream_none()}</EmptyNote>
{:else}
	<div class="flex flex-col gap-3">
		{#if stream.truncated}
			<p class="rounded-xl bg-lane-yellow px-3 py-2 text-sm text-lane-yellow-foreground">
				{m.stream_truncated()}
			</p>
		{/if}
		{#if phone.current}
			<ul class="flex flex-col gap-3" aria-label={m.stream_lanes()}>
				{#each lanes as lane, index (index)}
					{#if index === firstFolded}
						<li>{@render toggle()}</li>
					{/if}
					{#if shown(lane)}
						<li class={[cardVariants({ size: 'flush' }), 'p-3', lane.kind === 'branch' && 'ml-4']}>
							<p class="flex items-center gap-1 text-sm font-semibold">
								{#if lane.kind === 'branch'}
									<CornerDownRight class="size-4 text-muted-foreground" aria-hidden="true" />
								{/if}
								{laneTitle(lane, lookup)}
							</p>
							{#if joined(lane)}
								<p class="text-xs text-muted-foreground">{joined(lane)}</p>
							{:else if lane.number}
								<p class="font-mono text-xs text-muted-foreground">{lane.number}</p>
							{/if}
							<ol class="mt-2 flex flex-col gap-1.5 border-l-2 border-border pl-3">
								{#if lane.expected}<li>{@render expected(lane)}</li>{/if}
								{#each newestFirst(lane) as document (document.id)}
									<li>{@render chip(document)}</li>
								{/each}
								{#if lane.target}<li>{@render chip(lane.target, true)}</li>{/if}
							</ol>
						</li>
					{/if}
				{/each}
			</ul>
		{:else}
			<Card.Root size="flush" class="overflow-x-auto" bind:ref={scroller}>
				<div
					class="grid"
					style:grid-template-columns={columns}
					style:min-width={minWidth}
					role="table"
					aria-label={m.stream_lanes()}
				>
					<div role="row" class="contents">
						<div
							role="columnheader"
							class="sticky left-0 z-10 border-r border-b bg-card px-3 py-2 text-xs font-semibold text-muted-foreground"
						>
							{m.stream_lanes()}
						</div>
						{#each axis as column (column.kind === 'gap' ? column.from : column.month)}
							{#if column.kind === 'gap'}
								<div
									role="columnheader"
									class="border-b border-l bg-muted/40 px-2 py-2 text-center text-xs font-semibold text-muted-foreground"
									aria-label={gapLabel(column.months)}
									title={gapLabel(column.months)}
								>
									…
								</div>
							{:else}
								<div
									role="columnheader"
									class="border-b border-l px-2 py-2 text-xs font-semibold text-muted-foreground"
									data-month={column.month}
								>
									{monthLabel(column.month)}
								</div>
							{/if}
						{/each}
					</div>
					{#each lanes as lane, index (index)}
						{#if index === firstFolded}
							<div role="row" class="contents">
								<div
									role="cell"
									class="sticky left-0 z-10 border-r border-b bg-card px-2 py-1"
									style:grid-column="1 / -1"
								>
									{@render toggle()}
								</div>
							</div>
						{/if}
						{#if shown(lane)}
							<div role="row" class="contents">
								<div
									role="rowheader"
									class="sticky left-0 z-10 flex flex-col justify-center border-r border-b bg-card px-3 py-2"
									title={joined(lane) ?? laneTitle(lane, lookup)}
								>
									<span
										class={[
											'flex items-center gap-1 text-sm font-medium',
											lane.kind === 'branch' && 'pl-3'
										]}
									>
										{#if lane.kind === 'branch'}
											<CornerDownRight
												class="size-3.5 shrink-0 text-muted-foreground"
												aria-hidden="true"
											/>
										{/if}
										<span class="line-clamp-2">{laneTitle(lane, lookup)}</span>
									</span>
									{#if lane.number}
										<span class="truncate font-mono text-xs text-muted-foreground"
											>{lane.number}</span
										>
									{/if}
								</div>
								{#each axis as column (column.kind === 'gap' ? column.from : column.month)}
									{#if column.kind === 'gap'}
										<div role="cell" class="border-b border-l bg-muted/40"></div>
									{:else}
										<div role="cell" class="flex min-w-0 flex-col gap-1 border-b border-l p-1.5">
											{#if lane.target && monthOf(dayOf(lane.target)) === column.month}
												{@render chip(lane.target, true)}
											{/if}
											{#each inMonth(lane, column.month) as document (document.id)}
												{@render chip(document)}
											{/each}
											{#if lane.expected && monthOf(lane.expected.next_date) === column.month}
												{@render expected(lane)}
											{/if}
										</div>
									{/if}
								{/each}
							</div>
						{/if}
					{/each}
				</div>
			</Card.Root>
		{/if}
	</div>
{/if}
