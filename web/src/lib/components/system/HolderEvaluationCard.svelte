<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import HolderCasesDialog from '#lib/components/system/HolderCasesDialog.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { describeError } from '#lib/errors.ts';
	import {
		measureLabel,
		outcomeLabel,
		type HolderCases,
		type HolderOutcome
	} from '#lib/holder-cases.ts';
	import { dropEntry, entryOf, pushEntry } from '#lib/history-state.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { labelOfKind, type IdentifierKind } from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The holders against the decisions at the contacts (Tobi, 28.10.2026; admins): per kind
	// with a holder, how often the rule agreed with what was confirmed or rejected, the two ways
	// wrong apart (red above nought), the unclear and those read before their kind had a holder;
	// last the open list's recommendation, over every kind. The API keeps it for a minute. A
	// number above nought but "Stimmt" opens the cases behind it (`HolderCasesDialog`), kept in
	// the history entry as a dialog that opens the Beam is (web/DESIGN.md, "Beam").
	type Holders = components['schemas']['HoldersOut'];
	type Tally = components['schemas']['TallyOut'];

	const ORDER: IdentifierKind[] = ['iban', 'creditor_id', 'vat_id', 'email_domain'];

	let holders = $state<Holders | null>(null);
	let problem = $state<unknown>(null);

	async function load() {
		problem = null;
		try {
			holders = await unwrap(api.GET('/api/v1/automation/holders'));
		} catch (error) {
			problem = error;
		}
	}
	onMount(() => void load());

	// The kinds in a fixed order; one the API adds stands after them, as it comes.
	const rows = $derived.by(() => {
		if (!holders) return [];
		const ordered = ORDER.flatMap(
			(kind) => holders?.kinds.find((item) => item.kind === kind) ?? []
		);
		const rest = holders.kinds.filter((item) => !ORDER.includes(item.kind));
		return [...ordered, ...rest];
	});

	function told(tally: Tally): number {
		return tally.right + tally.learned_rejected + tally.refused_confirmed;
	}

	const opened = entryOf('holders');
	const wanted = $derived(opened() ?? null);

	function open(measure: HolderCases['measure'], outcome: HolderOutcome) {
		pushEntry('holders', { measure, outcome });
	}
</script>

{#snippet count(measure: HolderCases['measure'], outcome: HolderOutcome, value: number)}
	{#if value > 0}
		<button
			type="button"
			class="relative -mx-1.5 rounded-md px-1.5 tabular-nums underline decoration-dotted underline-offset-4 hover:bg-secondary max-sm:after:absolute max-sm:after:-inset-2.5"
			aria-label={m.holders_cases_open({
				count: formatNumber(value),
				measure: measureLabel(measure),
				outcome: outcomeLabel(outcome)
			})}
			onclick={() => open(measure, outcome)}>{formatNumber(value)}</button
		>
	{:else}
		{formatNumber(value)}
	{/if}
{/snippet}

{#snippet row(label: string, measure: HolderCases['measure'], tally: Tally, strong: boolean)}
	{@const of = told(tally)}
	<Table.Row>
		<Table.Cell class={cn(strong && 'font-semibold')}>{label}</Table.Cell>
		<Table.Cell class="text-right tabular-nums">
			{#if of > 0}
				<span class="font-medium">{formatNumber(tally.right)}</span>
				<span class="text-muted-foreground">{m.holders_of({ count: formatNumber(of) })}</span>
			{:else}
				<span class="text-muted-foreground">–</span>
			{/if}
		</Table.Cell>
		{#each ['learned_rejected', 'refused_confirmed'] as const as outcome (outcome)}
			{@const wrong = tally[outcome]}
			<Table.Cell
				class={cn(
					'text-right tabular-nums',
					wrong > 0 ? 'text-lane-red-foreground' : 'text-muted-foreground'
				)}
			>
				{#if of > 0}{@render count(measure, outcome, wrong)}{:else}–{/if}
			</Table.Cell>
		{/each}
		<Table.Cell class="text-right text-muted-foreground tabular-nums">
			{@render count(measure, 'unclear', tally.unclear)}
		</Table.Cell>
		<Table.Cell class="text-right text-muted-foreground tabular-nums">
			{#if strong}–{:else}{@render count(measure, 'unread', tally.unread)}{/if}
		</Table.Cell>
	</Table.Row>
{/snippet}

<Card.Root as="section" size="lg" class="flex flex-col gap-3">
	<div class="flex flex-col gap-1">
		<div class="flex items-center gap-1">
			<SectionTitle size="card">{m.holders_title()}</SectionTitle>
			<InfoTip label={m.hint_about({ name: m.holders_title() })} size="sm" class="w-80">
				<p>{m.holders_info()}</p>
			</InfoTip>
		</div>
		<p class="text-meta text-muted-foreground">{m.holders_hint()}</p>
	</div>
	{#if problem}
		<LoadProblem problem={describeError(problem)} onretry={load} />
	{:else if !holders}
		<Loading />
	{:else}
		<div class="overflow-x-auto">
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>{m.holders_kind()}</Table.Head>
						<Table.Head class="text-right">{m.holders_right()}</Table.Head>
						<Table.Head class="text-right">{m.holders_learned_rejected()}</Table.Head>
						<Table.Head class="text-right">{m.holders_refused_confirmed()}</Table.Head>
						<Table.Head class="text-right">{m.holders_unclear()}</Table.Head>
						<Table.Head class="text-right">{m.holders_unread()}</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each rows as item (item.kind)}
						{@render row(labelOfKind(item.kind), item.kind, item, false)}
					{/each}
					{@render row(m.holders_recommendation(), 'recommendation', holders.recommendation, true)}
				</Table.Body>
			</Table.Root>
		</div>
		<p class="text-meta text-muted-foreground">{m.holders_footnote()}</p>
	{/if}
</Card.Root>

<HolderCasesDialog {wanted} onclose={() => dropEntry('holders')} />
