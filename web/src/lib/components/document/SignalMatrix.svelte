<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { SIGNAL_NODES } from '#lib/signals.ts';
	import type { CellKind, MatrixRow } from '#lib/signal-matrix.ts';
	import { DOT } from '#lib/step-look.ts';
	import { cn } from '#lib/utils.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';

	// "Wer hat was erkannt?" (from mock A, Tobi 23.10.2026): per property the value and what
	// each signal said about it, as a mark; the number behind it on pointing. Narrow, each value
	// gets a chip that says in a word what made it green or that it is open (on a desktop the
	// marks say it: no column of its own, Tobi).
	let { rows, chips }: { rows: readonly MatrixRow[]; chips: boolean } = $props();

	// Flat shapes in the colours of the lane chips (Tobi, 23.10.2026): a circle names, a square
	// is evidence in the text, a diamond contradicts; rings for another value or silence.
	function mark(kind: CellKind, open: boolean): string {
		const fill = open ? DOT.yellow : DOT.green;
		switch (kind) {
			case 'names':
				return cn('size-4 rounded-full', fill);
			case 'evidence':
				return cn('size-4 rounded-xs', fill);
			case 'other':
				return 'size-4 rounded-full border-[1.5px] border-muted-foreground';
			case 'contradicts':
				return cn('mx-0.5 size-3 rotate-45 rounded-xs', DOT.red);
			case 'silent':
				return 'size-4 rounded-full border-[1.5px] border-dashed border-muted-foreground/60';
		}
	}

	function word(kind: CellKind, open: boolean): string {
		switch (kind) {
			case 'names':
				return open ? m.matrix_suggests() : m.matrix_names();
			case 'evidence':
				return m.matrix_evidence();
			case 'other':
				return m.matrix_other();
			case 'contradicts':
				return m.matrix_contradicts();
			case 'silent':
				return m.matrix_silent();
		}
	}

	const legend: { kind: CellKind; open: boolean }[] = [
		{ kind: 'names', open: false },
		{ kind: 'evidence', open: false },
		{ kind: 'names', open: true },
		{ kind: 'other', open: false },
		{ kind: 'contradicts', open: false },
		{ kind: 'silent', open: false }
	];
</script>

<Card.Root as="section" aria-labelledby="matrix-heading" class="flex min-w-0 flex-col gap-3">
	<div>
		<SectionTitle size="card" id="matrix-heading">{m.matrix_title()}</SectionTitle>
		<p class="mt-0.5 text-sm text-muted-foreground">{m.matrix_hint()}</p>
	</div>
	<Table.Root class="w-full table-fixed border-collapse text-sm">
		<colgroup>
			<col />
			{#each SIGNAL_NODES as signal (signal)}
				<col class={chips ? 'w-10' : 'w-28'} />
			{/each}
		</colgroup>
		<Table.Header>
			<Table.Row>
				<Table.Head scope="col" class="sr-only">{m.matrix_property()}</Table.Head>
				{#each SIGNAL_NODES as signal (signal)}
					<Table.Head
						scope="col"
						class={cn(
							'pb-2 text-center align-bottom font-normal text-muted-foreground',
							chips ? 'text-nano leading-tight hyphens-auto' : 'text-xs'
						)}
					>
						{NODE_LABELS[signal]()}
					</Table.Head>
				{/each}
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each rows as row (row.field)}
				<Table.Row class="border-t border-muted">
					<Table.Head scope="row" class="py-2.5 pr-2 text-left font-normal">
						<span class="flex min-w-0 items-start gap-2.5">
							{#if row.open}
								<TriangleAlert
									class="mt-0.5 size-4 shrink-0 text-lane-yellow-foreground"
									role="img"
									aria-label={m.matrix_open()}
									strokeWidth={2.2}
								/>
							{:else}
								<CircleCheck
									class="mt-0.5 size-4 shrink-0 text-lane-green-foreground"
									role="img"
									aria-label={m.matrix_decided()}
									strokeWidth={2.2}
								/>
							{/if}
							<span class="flex min-w-0 flex-col gap-0.5">
								<span class="text-xs text-muted-foreground">{row.label}</span>
								<span
									class={cn(
										'font-medium wrap-break-word hyphens-auto',
										row.open && 'text-lane-yellow-foreground'
									)}
								>
									{row.value}
								</span>
								{#if chips}
									<Badge variant={row.open ? 'yellow' : 'green'} class="self-start">
										{row.chip}
									</Badge>
								{/if}
							</span>
						</span>
					</Table.Head>
					{#each row.cells as cell (cell.signal)}
						<Table.Cell class="py-2.5 text-center" title={cell.title}>
							<span
								class={cn('inline-block align-middle', mark(cell.kind, row.open))}
								role="img"
								aria-label={`${NODE_LABELS[cell.signal]()}: ${word(cell.kind, row.open)}`}
							></span>
						</Table.Cell>
					{/each}
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
	<ul
		class="flex flex-wrap gap-x-4 gap-y-1.5 border-t border-muted pt-3 text-xs text-muted-foreground"
	>
		{#each legend as entry (`${entry.kind}-${entry.open}`)}
			<li class="flex items-center gap-1.5">
				<span class={cn('inline-block', mark(entry.kind, entry.open))} aria-hidden="true"></span>
				{word(entry.kind, entry.open)}
			</li>
		{/each}
	</ul>
</Card.Root>
