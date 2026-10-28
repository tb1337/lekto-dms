<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import * as Card from '#lib/components/ui/card/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { labelOfKind, type IdentifierKind } from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The holders against the decisions at the contacts (Tobi, 28.10.2026; admins): per kind
	// with a holder, how often the rule agreed with what was confirmed or rejected, the two ways
	// wrong apart (red above nought), the unclear and those read before their kind had a holder;
	// last the open list's recommendation, over every kind. The API keeps it for a minute.
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
</script>

{#snippet row(label: string, tally: Tally, strong: boolean)}
	{@const of = told(tally)}
	<Table.Row>
		<Table.Cell class={cn(strong && 'font-semibold')}>{label}</Table.Cell>
		<Table.Cell class="text-right tabular-nums">
			{#if of > 0}
				<span class="font-medium text-lane-green-foreground">{formatNumber(tally.right)}</span>
				<span class="text-muted-foreground">{m.holders_of({ count: formatNumber(of) })}</span>
			{:else}
				<span class="text-muted-foreground">–</span>
			{/if}
		</Table.Cell>
		{#each [tally.learned_rejected, tally.refused_confirmed] as wrong, index (index)}
			<Table.Cell
				class={cn(
					'text-right tabular-nums',
					wrong > 0 ? 'text-lane-red-foreground' : 'text-muted-foreground'
				)}>{of > 0 ? formatNumber(wrong) : '–'}</Table.Cell
			>
		{/each}
		<Table.Cell class="text-right text-muted-foreground tabular-nums">
			{formatNumber(tally.unclear)}
		</Table.Cell>
		<Table.Cell class="text-right text-muted-foreground tabular-nums">
			{strong ? '–' : formatNumber(tally.unread)}
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
						{@render row(labelOfKind(item.kind), item, false)}
					{/each}
					{@render row(m.holders_recommendation(), holders.recommendation, true)}
				</Table.Body>
			</Table.Root>
		</div>
		<p class="text-meta text-muted-foreground">{m.holders_footnote()}</p>
	{/if}
</Card.Root>
