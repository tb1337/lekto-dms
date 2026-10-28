<script lang="ts">
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { documentHref } from '#lib/candidates.ts';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { labelOfKind } from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';

	type Expected = components['schemas']['ExpectedOut'];
	type State = Expected['state'];
	type Cadence = Expected['cadence'];

	// The documents expected next (#145) on the overview (Tobi, 27.10.2026; until then a page of
	// its own): the series among the documents the user reads, the overdue ones and those of the
	// next 30 days, the later and ended ones on request, each with its rhythm, its spread and its
	// newest document. Only to look at.
	let all = $state(false);
	let found = $state<Expected[] | null>(null);
	let problem = $state<string | null>(null);
	let attempt = $state(0);
	// Overdue as the day is here.
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	$effect(() => {
		const allUsers = scope.query;
		void attempt;
		let current = true;
		void unwrap(
			api.GET('/api/v1/expected', { params: { query: { all_users: allUsers, tz: zone } } })
		).then(
			(items) => {
				if (!current) return;
				found = items;
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

	const SECTIONS: { state: State; title: () => string }[] = [
		{ state: 'overdue', title: m.expected_overdue },
		{ state: 'soon', title: m.expected_soon },
		{ state: 'later', title: m.expected_later },
		{ state: 'ended', title: m.expected_ended }
	];

	const CADENCES: Record<Exclude<Cadence, 'days'>, () => string> = {
		weekly: m.expected_weekly,
		monthly: m.expected_monthly,
		quarterly: m.expected_quarterly,
		half_yearly: m.expected_half_yearly,
		yearly: m.expected_yearly
	};

	function rhythm(item: Expected): string {
		const every =
			item.cadence === 'days'
				? m.expected_every_days({ count: String(item.interval_days) })
				: CADENCES[item.cadence]();
		return `${every} · ${m.expected_spread({ count: String(item.spread_days) })}`;
	}

	const SOON: readonly State[] = ['overdue', 'soon'];
	const every = $derived(
		SECTIONS.map((section) => ({
			...section,
			items: (found ?? []).filter((item) => item.state === section.state)
		})).filter((section) => section.items.length > 0)
	);
	const sections = $derived(every.filter((section) => all || SOON.includes(section.state)));
	const hidden = $derived((found ?? []).filter((item) => !SOON.includes(item.state)).length);
</script>

<section class="flex flex-col gap-3" aria-labelledby="expected-title">
	<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
		<SectionTitle id="expected-title">{m.nav_expected()}</SectionTitle>
		<span class="text-meta text-muted-foreground">{m.expected_hint()}</span>
	</div>
	{#if problem}
		<LoadProblem {problem} onretry={() => attempt++} />
	{:else if !found}
		<Loading />
	{:else if found.length === 0}
		<EmptyNote compact>{m.expected_none()}</EmptyNote>
	{:else}
		{#if sections.length === 0}
			<p class="text-muted-foreground">{m.overview_expected_nothing_soon()}</p>
		{/if}
		{#each sections as section (section.state)}
			<section class="flex flex-col gap-2" aria-labelledby="expected-{section.state}">
				<SectionTitle id="expected-{section.state}" level={3} size="card">
					{section.title()}
					<span class="font-normal text-muted-foreground">{section.items.length}</span>
				</SectionTitle>
				<ul class="flex flex-col gap-2">
					{#each section.items as item (item.last.id)}
						<Card.Root as="li" size="row" class="flex flex-wrap items-center gap-3">
							<CalendarClock class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
							<div class="flex min-w-0 flex-1 flex-col gap-1">
								<span class="flex flex-wrap items-center gap-2 font-medium">
									<span class="min-w-0 break-words"
										>{item.contact.name} · {item.document_type.name}</span
									>
									{#if item.number}
										<Badge variant="outline" class="max-w-full min-w-0">
											<span class="truncate"
												>{labelOfKind(item.number.kind)} {item.number.value}</span
											>
										</Badge>
									{/if}
								</span>
								<span class="text-sm text-muted-foreground">
									{rhythm(item)} · {m.expected_documents({ count: String(item.documents) })}
								</span>
								<span class="text-sm text-muted-foreground">
									{m.expected_last()}
									<a
										href={documentHref(item.last.id)}
										class="text-foreground underline-offset-2 hover:underline">{item.last.title}</a
									>
									({formatDate(item.last.document_date)})
								</span>
							</div>
							<div class="flex flex-col items-end gap-0.5 text-right">
								<span
									class="text-sm font-semibold {item.state === 'overdue' ? 'text-destructive' : ''}"
									>{item.state === 'ended'
										? m.expected_was({ date: formatDate(item.next_date) })
										: m.expected_next({ date: formatDate(item.next_date) })}</span
								>
								{#if item.next_period}
									<span class="text-xs text-muted-foreground"
										>{m.expected_for({ period: item.next_period })}</span
									>
								{/if}
							</div>
						</Card.Root>
					{/each}
				</ul>
			</section>
		{/each}
		{#if hidden > 0}
			<div>
				<Button variant="link" size="inline" onclick={() => (all = !all)}>
					{all ? m.overview_expected_less() : m.overview_expected_more({ count: String(hidden) })}
				</Button>
			</div>
		{/if}
	{/if}
</section>
