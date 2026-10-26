<script lang="ts">
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import CornerDownRight from '@lucide/svelte/icons/corner-down-right';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { documentHref } from '#lib/candidates.ts';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { describeError } from '#lib/errors.ts';
	import type { apiQuery } from '#lib/filters.ts';
	import { formatDate } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import {
		dayOf,
		inMonth,
		laneTitle,
		monthOf,
		monthsOf,
		type StreamDocument,
		type StreamLane,
		type StreamOut
	} from '#lib/stream.ts';

	// The documents of the filters in lanes (#145): a series with its relation target at the
	// start and its expected document at the end, branches off it, chains, and the rest. On the
	// desktop the months run from left to right; on a phone each lane runs down, newest first.
	let { query, lookup }: { query: ReturnType<typeof apiQuery>; lookup: Lookup | null } = $props();

	let stream = $state<StreamOut | null>(null);
	let problem = $state<string | null>(null);
	let attempt = $state(0);

	$effect(() => {
		const asked = query;
		void attempt;
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

	const months = $derived(stream ? monthsOf(stream) : []);
	// The lane names, then one column per month.
	const columns = $derived(`13rem repeat(${months.length}, minmax(7.5rem, 1fr))`);
	const titles = $derived(new Map((stream?.lanes ?? []).map((lane, index) => [index, lane])));

	function joined(lane: StreamLane): string | null {
		if (lane.parent === null || lane.parent === undefined || !stream) return null;
		const parent = titles.get(lane.parent);
		const document = [
			...(parent?.documents ?? []),
			...(parent?.target ? [parent.target] : [])
		].find((item) => item.id === lane.joins);
		return document ? m.stream_joins({ title: document.title }) : null;
	}

	const monthLabel = (month: string) =>
		formatDate(`${month}-01`, { month: 'short', year: '2-digit' });
	const short = (document: StreamDocument) =>
		formatDate(dayOf(document), { day: '2-digit', month: '2-digit' });
	/** Newest first, as on a phone: the expected one on top, the target at the bottom. */
	const newestFirst = (lane: StreamLane) => [...lane.documents].reverse();
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
			>{target ? `${m.stream_target()} · ` : ''}{short(document)}</span
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

{#if problem}
	<LoadProblem {problem} onretry={() => attempt++} />
{:else if !stream}
	<p class="text-muted-foreground">{m.loading()}</p>
{:else if stream.lanes.length === 0}
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
				{#each stream.lanes as lane, index (index)}
					<li class={['rounded-2xl border bg-card p-3', lane.kind === 'branch' && 'ml-4']}>
						<p class="flex items-center gap-1 text-sm font-semibold">
							{#if lane.kind === 'branch'}
								<CornerDownRight class="size-4 text-muted-foreground" aria-hidden="true" />
							{/if}
							{laneTitle(lane, lookup)}
						</p>
						{#if joined(lane)}
							<p class="text-xs text-muted-foreground">{joined(lane)}</p>
						{/if}
						<ol class="mt-2 flex flex-col gap-1.5 border-l-2 border-border pl-3">
							{#if lane.expected}<li>{@render expected(lane)}</li>{/if}
							{#each newestFirst(lane) as document (document.id)}
								<li>{@render chip(document)}</li>
							{/each}
							{#if lane.target}<li>{@render chip(lane.target, true)}</li>{/if}
						</ol>
					</li>
				{/each}
			</ul>
		{:else}
			<div class="overflow-x-auto rounded-2xl border bg-card">
				<div
					class="grid min-w-max"
					style:grid-template-columns={columns}
					role="table"
					aria-label={m.stream_lanes()}
				>
					<div role="row" class="contents">
						<div
							role="columnheader"
							class="sticky left-0 z-10 border-b bg-card px-3 py-2 text-xs font-semibold text-muted-foreground"
						>
							{m.stream_lanes()}
						</div>
						{#each months as month (month)}
							<div
								role="columnheader"
								class="border-b border-l px-2 py-2 text-xs font-semibold text-muted-foreground"
							>
								{monthLabel(month)}
							</div>
						{/each}
					</div>
					{#each stream.lanes as lane, index (index)}
						<div role="row" class="contents">
							<div
								role="rowheader"
								class="sticky left-0 z-10 flex flex-col justify-center border-b bg-card px-3 py-2"
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
									<span class="line-clamp-2" title={laneTitle(lane, lookup)}
										>{laneTitle(lane, lookup)}</span
									>
								</span>
								{#if joined(lane)}
									<span class="truncate pl-3 text-xs text-muted-foreground">{joined(lane)}</span>
								{:else if lane.number}
									<span class="truncate font-mono text-xs text-muted-foreground">{lane.number}</span
									>
								{/if}
							</div>
							{#each months as month (month)}
								<div role="cell" class="flex min-w-0 flex-col gap-1 border-b border-l p-1.5">
									{#if lane.target && monthOf(dayOf(lane.target)) === month}
										{@render chip(lane.target, true)}
									{/if}
									{#each inMonth(lane, month) as document (document.id)}
										{@render chip(document)}
									{/each}
									{#if lane.expected && monthOf(lane.expected.next_date) === month}
										{@render expected(lane)}
									{/if}
								</div>
							{/each}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}
