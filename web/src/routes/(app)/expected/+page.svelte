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
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';

	type Expected = components['schemas']['ExpectedOut'];
	type State = Expected['state'];
	type Cadence = Expected['cadence'];

	// The documents expected next (#145): the series among the documents the user reads, in
	// four sections, each with its rhythm, its spread and its newest document. Only to look at.
	let found = $state<Expected[] | null>(null);
	let problem = $state<string | null>(null);
	let attempt = $state(0);

	$effect(() => {
		const allUsers = scope.query;
		void attempt;
		let current = true;
		void unwrap(api.GET('/api/v1/expected', { params: { query: { all_users: allUsers } } })).then(
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

	const sections = $derived(
		SECTIONS.map((section) => ({
			...section,
			items: (found ?? []).filter((item) => item.state === section.state)
		})).filter((section) => section.items.length > 0)
	);
</script>

<svelte:head><title>{m.nav_expected()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-col gap-1">
		<h1 class="text-[1.75rem] font-semibold tracking-tight">{m.nav_expected()}</h1>
		<p class="text-sm text-muted-foreground">{m.expected_hint()}</p>
	</div>

	{#if problem}
		<LoadProblem {problem} onretry={() => attempt++} />
	{:else if !found}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else if found.length === 0}
		<EmptyNote>{m.expected_none()}</EmptyNote>
	{:else}
		{#each sections as section (section.state)}
			<section class="flex flex-col gap-2" aria-labelledby="expected-{section.state}">
				<h2 id="expected-{section.state}" class="text-base font-semibold">
					{section.title()}
					<span class="font-normal text-muted-foreground">{section.items.length}</span>
				</h2>
				<ul class="flex flex-col gap-2">
					{#each section.items as item (`${item.contact.id}:${item.document_type.id}:${item.number?.value ?? ''}`)}
						<li class="flex flex-wrap items-center gap-3 rounded-2xl border bg-card p-4">
							<CalendarClock class="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
							<div class="flex min-w-0 flex-1 flex-col gap-1">
								<span class="flex flex-wrap items-center gap-2 font-medium">
									<span class="min-w-0 break-words"
										>{item.contact.name} · {item.document_type.name}</span
									>
									{#if item.number}
										<Badge variant="outline" class="font-mono">{item.number.value}</Badge>
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
									>{formatDate(item.next_date)}</span
								>
								{#if item.next_period}
									<span class="text-xs text-muted-foreground"
										>{m.expected_for({ period: item.next_period })}</span
									>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	{/if}
</div>
