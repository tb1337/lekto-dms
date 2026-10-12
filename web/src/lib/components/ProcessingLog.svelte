<script lang="ts">
	import { untrack } from 'svelte';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { events } from '#lib/events.svelte.ts';
	import { formatDate, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';

	type Node = components['schemas']['Node'];
	type Outcome = components['schemas']['Outcome'];

	type LogEntry = components['schemas']['LogEntry'];

	// What each node did: result, confidence, reason, model and duration, grouped by node in
	// graph order, the runs of a node oldest first.
	let { documentId }: { documentId: string } = $props();

	let entries = $state<LogEntry[] | null>(null);
	let problem = $state<string | null>(null);

	const ORDER: Node[] = [
		'receive',
		'ocr',
		'pages',
		'parse',
		'classify',
		'extract_fields',
		'apply_rules',
		'file'
	];
	const groups = $derived.by(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- built and read at once
		const byNode = new Map<Node, LogEntry[]>();
		for (const entry of entries ?? []) {
			const list = byNode.get(entry.node) ?? [];
			list.push(entry);
			byNode.set(entry.node, list);
		}
		return [...byNode.entries()].sort(([a], [b]) => ORDER.indexOf(a) - ORDER.indexOf(b));
	});

	const nodeLabel: Record<Node, () => string> = {
		receive: m.node_receive,
		ocr: m.node_ocr,
		pages: m.node_pages,
		parse: m.node_parse,
		classify: m.node_classify,
		extract_fields: m.node_extract_fields,
		apply_rules: m.node_apply_rules,
		file: m.node_file
	};
	const outcomeLabel: Record<Outcome, () => string> = {
		ok: m.outcome_ok,
		uncertain: m.outcome_uncertain,
		failed: m.outcome_failed
	};

	// An answer for a document the page has left behind must not replace the current one.
	async function load() {
		const wanted = documentId;
		try {
			const loaded = await unwrap(
				api.GET('/api/v1/documents/{id}/log', { params: { path: { id: wanted } } })
			);
			if (wanted === documentId) {
				entries = loaded;
				problem = null;
			}
		} catch (error) {
			if (wanted === documentId) problem = describeError(error);
		}
	}

	$effect(() => {
		void documentId;
		untrack(() => {
			entries = null;
			problem = null;
		});
		void events.generation;
		void load();
		return events.subscribe((event) => {
			if (event.document_id === documentId && event.type === 'document.node_completed') void load();
		});
	});
</script>

{#if problem}
	<p class="text-destructive" role="alert">{problem}</p>
{:else if entries === null}
	<p class="text-muted-foreground">{m.loading()}</p>
{:else if entries.length === 0}
	<p class="text-muted-foreground">{m.log_none()}</p>
{:else}
	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>{m.log_node()}</Table.Head>
				<Table.Head>{m.log_outcome()}</Table.Head>
				<Table.Head>{m.log_confidence()}</Table.Head>
				<Table.Head>{m.log_reason()}</Table.Head>
				<Table.Head>{m.log_model()}</Table.Head>
				<Table.Head>{m.log_duration()}</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each groups as [node, runs] (node)}
				{#each runs as entry, index (`${entry.run}-${entry.node}-${entry.started_at}`)}
					<Table.Row data-node={node}>
						<Table.Cell>
							{#if index === 0}{nodeLabel[node]()}{/if}
							<span class="block text-xs text-muted-foreground">
								{m.log_run({ run: entry.run })} · {formatDate(entry.started_at, {
									dateStyle: 'short',
									timeStyle: 'short'
								})}
							</span>
						</Table.Cell>
						<Table.Cell>{outcomeLabel[entry.outcome]()}</Table.Cell>
						<Table.Cell>
							{entry.confidence === null
								? '–'
								: formatNumber(entry.confidence, { style: 'percent', maximumFractionDigits: 0 })}
						</Table.Cell>
						<Table.Cell class="max-w-xs whitespace-normal">{entry.reason ?? '–'}</Table.Cell>
						<Table.Cell>{entry.model_version ?? '–'}</Table.Cell>
						<Table.Cell
							>{formatNumber(entry.duration_ms / 1000, {
								style: 'unit',
								unit: 'second',
								unitDisplay: 'narrow',
								maximumFractionDigits: 1
							})}</Table.Cell
						>
					</Table.Row>
				{/each}
			{/each}
		</Table.Body>
	</Table.Root>
{/if}
