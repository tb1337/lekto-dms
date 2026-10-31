<script lang="ts">
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import { openBeam } from '#lib/beam.svelte.ts';
	import BeamTitle from '#lib/components/BeamTitle.svelte';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { shown } from '#lib/facts.ts';
	import {
		casesText,
		measureLabel,
		outcomeLabel,
		wrong,
		type HolderCases
	} from '#lib/holder-cases.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { latest } from '#lib/latest.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The decisions behind one number of the holders' evaluation (mock "Ort 7", Tobi 30.10.2026):
	// each identifier with its contact, the person's decision (red where the measure was wrong)
	// and in how many confirmed documents of the contact it stands. Its value, the eye before it,
	// shows those documents in the Beam, the identifier marked; the Beam lies over the dialog.
	type Case = components['schemas']['HolderCaseOut'];

	const MAX = 100;

	let { wanted, onclose }: { wanted: HolderCases | null; onclose: () => void } = $props();

	let cases = $state<Case[] | null>(null);
	let problem = $state<string | null>(null);
	const begin = latest();

	async function load(asked: HolderCases) {
		const current = begin();
		cases = null;
		problem = null;
		try {
			const found = await unwrap(
				api.GET('/api/v1/automation/holders/cases', {
					params: { query: { measure: asked.measure, outcome: asked.outcome } }
				})
			);
			if (current()) cases = found.cases;
		} catch (error) {
			if (current()) problem = describeError(error);
		}
	}

	$effect(() => {
		if (wanted) void load(wanted);
	});

	const title = $derived(
		wanted
			? m.holders_cases_title({
					measure: measureLabel(wanted.measure),
					outcome: outcomeLabel(wanted.outcome)
				})
			: ''
	);

	function view(item: Case) {
		const [first] = item.document_ids;
		if (!first) return;
		openBeam(item.document_ids, first, title, {
			source: { kind: 'fact', identifier: item.kind, ref: item.ref }
		});
	}
</script>

<Dialog.Root open={wanted !== null} onOpenChange={(open) => !open && onclose()}>
	<Dialog.Content size="lg">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{wanted ? casesText(wanted) : ''}</Dialog.Description>
		</Dialog.Header>
		{#if problem}
			<LoadProblem {problem} onretry={() => wanted && load(wanted)} />
		{:else if !cases}
			<Loading />
		{:else if cases.length === 0}
			<EmptyNote compact>{m.holders_cases_none()}</EmptyNote>
		{:else}
			<ul class="flex flex-col gap-2">
				{#each cases as item (`${item.kind}:${item.value}:${item.contact_id}`)}
					<Card.Root
						as="li"
						size="sm"
						class="flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-nowrap"
					>
						<!-- The value opens the Beam; on a phone the rest stands below it. -->
						<BeamTitle
							title={shown(item)}
							label={m.holders_cases_view({ value: shown(item) })}
							mono
							disabled={item.document_ids.length === 0}
							class="flex-1 max-sm:basis-full"
							onview={() => view(item)}
						/>
						<span class="min-w-0 truncate text-meta">{item.contact}</span>
						<Badge variant={wrong(wanted?.outcome ?? 'right') ? 'red' : 'muted'} class="shrink-0">
							{item.confirmed ? m.holders_cases_confirmed() : m.holders_cases_rejected()}
						</Badge>
						<span class="shrink-0 text-meta text-muted-foreground tabular-nums">
							{item.document_ids.length === 1
								? m.master_documents_one()
								: m.master_documents({ count: formatNumber(item.document_ids.length) })}
						</span>
					</Card.Root>
				{/each}
			</ul>
			{#if cases.length >= MAX}
				<p class="text-meta text-muted-foreground">
					{m.holders_cases_first({ count: formatNumber(MAX) })}
				</p>
			{/if}
			<p class="text-meta text-muted-foreground">{m.holders_cases_beam()}</p>
		{/if}
	</Dialog.Content>
</Dialog.Root>
