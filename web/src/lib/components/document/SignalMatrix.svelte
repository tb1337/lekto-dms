<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { SIGNAL_NODES } from '#lib/signals.ts';
	import type { CellKind, MatrixRow } from '#lib/signal-matrix.ts';
	import { cn } from '#lib/utils.ts';

	// "Wer hat was erkannt?" (from mock A, Tobi 23.10.2026): per property the value and what
	// each signal said about it, as a mark; the number behind it on pointing. Narrow, each value
	// gets a chip that says in a word what made it green or that it is open (on a desktop the
	// marks say it: no column of its own, Tobi).
	let { rows, chips }: { rows: readonly MatrixRow[]; chips: boolean } = $props();

	function mark(kind: CellKind, open: boolean): string {
		const fill = open ? 'bg-lane-yellow-foreground' : 'bg-lane-green-foreground';
		switch (kind) {
			case 'names':
				return cn('size-3.5 rounded-full', fill);
			case 'evidence':
				return cn('size-3.5 rounded-[4px]', fill);
			case 'other':
				return 'size-3.5 rounded-full border-2 border-muted-foreground/70';
			case 'contradicts':
				return 'size-3.5 rounded-full border-2 border-lane-red-foreground';
			case 'silent':
				return 'size-3.5 rounded-full border-2 border-dashed border-muted-foreground/50';
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

<section
	aria-labelledby="matrix-heading"
	class="flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-5"
>
	<div>
		<h2 id="matrix-heading" class="font-semibold">{m.matrix_title()}</h2>
		<p class="mt-0.5 text-sm text-muted-foreground">{m.matrix_hint()}</p>
	</div>
	<table class="w-full table-fixed border-collapse text-sm">
		<colgroup>
			<col />
			{#each SIGNAL_NODES as signal (signal)}
				<col class={chips ? 'w-10' : 'w-28'} />
			{/each}
		</colgroup>
		<thead>
			<tr>
				<th scope="col" class="sr-only">{m.matrix_property()}</th>
				{#each SIGNAL_NODES as signal (signal)}
					<th
						scope="col"
						class={cn(
							'pb-2 text-center align-bottom font-normal text-muted-foreground',
							chips ? 'text-[10px] leading-tight hyphens-auto' : 'text-xs'
						)}
					>
						{NODE_LABELS[signal]()}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.field)}
				<tr class="border-t border-muted">
					<th scope="row" class="py-2.5 pr-2 text-left font-normal">
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
									<span
										class={cn(
											'self-start rounded-full px-2 py-0.5 text-[11px] font-medium',
											row.open
												? 'bg-lane-yellow text-lane-yellow-foreground'
												: 'bg-lane-green text-lane-green-foreground'
										)}
									>
										{row.chip}
									</span>
								{/if}
							</span>
						</span>
					</th>
					{#each row.cells as cell (cell.signal)}
						<td class="py-2.5 text-center" title={cell.title}>
							<span
								class={cn('inline-block align-middle', mark(cell.kind, row.open))}
								role="img"
								aria-label={`${NODE_LABELS[cell.signal]()}: ${word(cell.kind, row.open)}`}
							></span>
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
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
</section>
