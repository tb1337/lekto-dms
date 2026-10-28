<script lang="ts" module>
	import type { components } from '#lib/api/schema.ts';
	import type { apiQuery } from '#lib/filters.ts';

	/** The documents an action is for: `ids` one by one, else every hit of `query` (the
	 * filters, with `q` the words). */
	export interface BulkSelection {
		ids: string[] | null;
		query: Partial<ReturnType<typeof apiQuery>> & { q?: string };
	}

	export type BulkOperation = components['schemas']['BulkOperationOut'];
</script>

<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import SearchSelect from '#lib/components/SearchSelect.svelte';
	import Select from '#lib/components/Select.svelte';
	import TagPicker from '#lib/components/TagPicker.svelte';
	import BulkSkipped from '#lib/components/BulkSkipped.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Progress } from '#lib/components/ui/progress/index.ts';
	import { reportError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { spaceOptions, type Lookup } from '#lib/masterdata.svelte.ts';
	import { NODE_LABELS } from '#lib/node-labels.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { descendants, pipeline, type GraphNode } from '#lib/pipeline.ts';
	import { session } from '#lib/session.svelte.ts';
	import { tagOptions } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';
	import { bulkDocuments, bulkResult, MODEL_CALLS, WARN_ABOVE } from '#lib/bulk.ts';

	type Action = components['schemas']['BulkActionIn'];
	type ReprocessNode = components['schemas']['ReprocessNode'];

	// The selection bar of the documents list (web/DESIGN.md, "Choosing many"): how many are
	// chosen, "Alle N Treffer auswählen" once the whole page is, "Auswahl aufheben" and the
	// actions (Tags, Kontakt, Typ, and under "Mehr" Thema, Space, Bestätigen, Neu verarbeiten,
	// Löschen). Each action but confirming opens its dialog; deleting and reprocessing name the
	// exact count. The action runs in the background (`POST /documents/bulk`): the bar shows how
	// far it has come and a toast what it did, with the skipped ones behind "Details".
	let {
		count,
		all,
		offerAll,
		limit,
		capped,
		selection,
		lookup,
		onall,
		onclear,
		ondone,
		busy = $bindable(false)
	}: {
		/** How many documents are chosen. */
		count: number;
		/** Every hit of the search and filters is chosen, not ids. */
		all: boolean;
		/** The hits to offer "Alle N Treffer auswählen" for (the whole page is chosen). */
		offerAll: number | null;
		/** More hits than one action takes: the most it takes. */
		limit: number | null;
		/** The search reaches fewer hits than it found. */
		capped: number | null;
		selection: () => BulkSelection;
		lookup: Lookup | null;
		onall: () => void;
		onclear: () => void;
		/** The action has ended: the list loads again. */
		ondone: () => void;
		/** An action runs: the bar stays until it ends. */
		busy?: boolean;
	} = $props();

	let running = $state<BulkOperation | null>(null);
	let skipped = $state<BulkOperation | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;
	onDestroy(() => clearTimeout(timer));

	let dialog = $state<
		'tags' | 'contact' | 'type' | 'topic' | 'move' | 'reprocess' | 'delete' | null
	>(null);
	const open = (which: typeof dialog) => () => (dialog = which);
	/** The `open` of the dialog `which`, to bind. */
	const shown = (which: NonNullable<typeof dialog>) => dialog === which;
	const showing = (which: NonNullable<typeof dialog>) => (value: boolean) => {
		if (value) dialog = which;
		else if (dialog === which) dialog = null;
	};

	let adding = $state<string[]>([]);
	let removing = $state<string[]>([]);
	let contact = $state('');
	let documentType = $state('');
	let topic = $state('');
	let space = $state('');
	let fromNode = $state<ReprocessNode>('ocr');
	let graph = $state<GraphNode[]>([]);

	const documents = $derived(bulkDocuments(count));
	const spaces = $derived(lookup ? spaceOptions(lookup.spaces, lookup.users, session.user) : []);
	const nodes = $derived(
		graph
			.map((entry) => entry.node)
			.filter((node): node is ReprocessNode => node !== 'receive')
			.map((node) => ({ value: node, label: NODE_LABELS[node]() }))
	);
	// From the model's step on, every document asks the model (proposal and facts).
	const asksModel = $derived(
		fromNode === 'signal_llm' || descendants(graph, fromNode).has('signal_llm')
	);

	async function startReprocess() {
		dialog = 'reprocess';
		if (graph.length === 0) {
			try {
				graph = (await pipeline()).nodes;
			} catch (error) {
				reportError(error);
			}
		}
	}

	/** Start `action` on the selection; the bar follows it until it ends. */
	async function start(action: Action) {
		const { ids, query } = selection();
		const operation = await unwrap(
			api.POST('/api/v1/documents/bulk', {
				params: { query: ids ? {} : query },
				body: { document_ids: ids, action }
			})
		);
		dialog = null;
		running = operation;
		busy = true;
		follow(operation.id);
	}

	function follow(id: string) {
		timer = setTimeout(async () => {
			try {
				const operation = await unwrap(
					api.GET('/api/v1/documents/bulk/{id}', { params: { path: { id } } })
				);
				running = operation;
				if (operation.status === 'done' || operation.status === 'failed') {
					finish(operation);
					return;
				}
			} catch {
				// A hiccup of the connection: ask again.
			}
			follow(id);
		}, 1000);
	}

	function finish(operation: BulkOperation) {
		running = null;
		busy = false;
		const result = bulkResult(operation);
		if (operation.status === 'failed') {
			toast.error(m.bulk_failed(), { description: result });
		} else if (operation.skipped.length > 0) {
			toast.warning(result, {
				description: m.bulk_skipped({ count: formatNumber(operation.skipped.length) }),
				action: { label: m.bulk_details(), onClick: () => (skipped = operation) }
			});
		} else {
			toast.success(result);
		}
		ondone();
	}

	async function confirmAll() {
		try {
			await start({ kind: 'confirm' });
		} catch (error) {
			reportError(error);
		}
	}

	function reset() {
		adding = [];
		removing = [];
		contact = '';
		documentType = '';
		topic = '';
		space = '';
	}
	$effect(() => {
		if (dialog === null) reset();
	});
</script>

<div
	class={cn(
		'flex flex-wrap items-center gap-x-3 gap-y-2',
		phone.current
			? 'sticky bottom-0 z-10 -mx-4 border-t bg-card px-4 pt-3 pb-4'
			: 'sticky top-20 z-10 rounded-2xl border bg-panel py-2 pr-2 pl-4'
	)}
	role="region"
	aria-label={m.bulk_selected({ count: formatNumber(count) })}
	aria-busy={busy}
>
	<span class="font-medium">{m.bulk_selected({ count: formatNumber(count) })}</span>
	{#if running}
		<span class="flex min-w-0 flex-1 items-center gap-3 text-meta text-muted-foreground">
			<Progress
				value={running.done}
				max={Math.max(running.total, 1)}
				class="max-w-48"
				aria-label={m.bulk_running({
					done: formatNumber(running.done),
					total: formatNumber(running.total)
				})}
			/>
			<span aria-live="polite">
				{m.bulk_running({ done: formatNumber(running.done), total: formatNumber(running.total) })}
			</span>
		</span>
	{:else}
		<span class="text-meta text-muted-foreground max-sm:order-last max-sm:basis-full sm:flex-1">
			{#if all}
				{m.bulk_all_hits()}
				{#if capped !== null}{m.bulk_capped({ count: formatNumber(capped) })}{/if}
			{:else if limit !== null}
				{m.bulk_limit({ max: formatNumber(limit) })}
			{:else if offerAll !== null}
				<Button variant="link" size="inline" onclick={onall}>
					{m.bulk_select_all({ count: formatNumber(offerAll) })}
				</Button>
			{/if}
		</span>
		<Button variant="ghost" size="sm" onclick={onclear}>{m.bulk_clear()}</Button>
		<div class={cn('flex gap-2', phone.current && 'grid flex-1 basis-full grid-cols-4')}>
			<Button variant="outline" size="sm" onclick={open('tags')}>{m.field_tags()}</Button>
			<Button variant="outline" size="sm" onclick={open('contact')}>{m.field_contact()}</Button>
			<Button variant="outline" size="sm" onclick={open('type')}>{m.bulk_type()}</Button>
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button {...props} variant="outline" size="sm">
							{m.bulk_more()}
							<ChevronDown aria-hidden="true" />
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="end" class="w-56">
					<DropdownMenu.Item onSelect={open('topic')}>{m.bulk_set_topic()}</DropdownMenu.Item>
					<DropdownMenu.Item onSelect={open('move')}>{m.bulk_move()}</DropdownMenu.Item>
					<DropdownMenu.Item onSelect={confirmAll}>{m.bulk_confirm()}</DropdownMenu.Item>
					<DropdownMenu.Item onSelect={startReprocess}>{m.bulk_reprocess()}</DropdownMenu.Item>
					<DropdownMenu.Separator />
					<DropdownMenu.Item variant="destructive" onSelect={open('delete')}>
						{m.bulk_delete()}
					</DropdownMenu.Item>
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		</div>
	{/if}
</div>

{#if lookup}
	<FormDialog
		bind:open={() => shown('tags'), showing('tags')}
		title={m.bulk_tags_title()}
		description={m.bulk_hint({ documents })}
		submitLabel={m.bulk_change()}
		disabled={adding.length === 0 && removing.length === 0}
		action={() => start({ kind: 'change_tags', add_tag_ids: adding, remove_tag_ids: removing })}
	>
		<Field.Field>
			<Field.Label id="bulk-add-label">{m.bulk_add()}</Field.Label>
			<TagPicker
				id="bulk-add"
				label={m.bulk_add()}
				labelledby="bulk-add-label"
				title={m.field_tags()}
				scope="document"
				tags={lookup.tags}
				selected={adding}
				onchange={(next) => (adding = next)}
				offered={(tag) => !removing.includes(tag.id)}
			/>
		</Field.Field>
		<Field.Field>
			<Field.Label id="bulk-remove-label">{m.bulk_remove()}</Field.Label>
			<TagPicker
				id="bulk-remove"
				label={m.bulk_remove()}
				labelledby="bulk-remove-label"
				title={m.field_tags()}
				scope="document"
				tags={lookup.tags}
				selected={removing}
				onchange={(next) => (removing = next)}
				offered={(tag) => !adding.includes(tag.id)}
			/>
		</Field.Field>
	</FormDialog>

	<FormDialog
		bind:open={() => shown('contact'), showing('contact')}
		title={m.bulk_contact_title()}
		description={m.bulk_hint({ documents })}
		submitLabel={m.bulk_set()}
		action={() => start({ kind: 'set_contact', contact_id: contact || null })}
	>
		<Field.Field>
			<Field.Label for="bulk-contact">{m.field_contact()}</Field.Label>
			<SearchSelect
				id="bulk-contact"
				title={m.picker_title_contact()}
				bind:value={contact}
				options={lookup.contacts.map((entry) => ({
					value: entry.id,
					label: entry.name,
					keywords: entry.aliases?.join(' ')
				}))}
				placeholder={m.value_unset()}
				noneLabel={m.value_unset()}
			/>
		</Field.Field>
	</FormDialog>

	<FormDialog
		bind:open={() => shown('type'), showing('type')}
		title={m.bulk_type_title()}
		description={m.bulk_hint({ documents })}
		submitLabel={m.bulk_set()}
		action={() => start({ kind: 'set_document_type', document_type_id: documentType || null })}
	>
		<Field.Field>
			<Field.Label for="bulk-type">{m.field_document_type()}</Field.Label>
			<SearchSelect
				id="bulk-type"
				title={m.picker_title_type()}
				bind:value={documentType}
				options={lookup.documentTypes.map((entry) => ({ value: entry.id, label: entry.name }))}
				placeholder={m.value_unset()}
				noneLabel={m.value_unset()}
			/>
		</Field.Field>
	</FormDialog>

	<FormDialog
		bind:open={() => shown('topic'), showing('topic')}
		title={m.bulk_topic_title()}
		description={m.bulk_hint({ documents })}
		submitLabel={m.bulk_set()}
		action={() => start({ kind: 'set_topic', topic_id: topic || null })}
	>
		<Field.Field>
			<Field.Label for="bulk-topic">{m.field_topic()}</Field.Label>
			<SearchSelect
				id="bulk-topic"
				title={m.picker_title_topic()}
				bind:value={topic}
				options={tagOptions(lookup.tags, 'topic')}
				placeholder={m.value_unset()}
				noneLabel={m.value_unset()}
			/>
		</Field.Field>
	</FormDialog>

	<FormDialog
		bind:open={() => shown('move'), showing('move')}
		title={m.bulk_move_title()}
		description={m.bulk_hint({ documents })}
		submitLabel={m.move_title()}
		disabled={!space}
		action={() => start({ kind: 'move', space_id: space })}
	>
		<Field.Field>
			<Field.Label for="bulk-space">{m.field_space()}</Field.Label>
			<Select id="bulk-space" bind:value={space} options={spaces} />
		</Field.Field>
	</FormDialog>

	<FormDialog
		bind:open={() => shown('reprocess'), showing('reprocess')}
		title={m.bulk_reprocess_title({ documents })}
		description={m.reprocess_hint()}
		submitLabel={m.reprocess_title()}
		disabled={nodes.length === 0}
		action={() => start({ kind: 'reprocess', from_node: fromNode })}
	>
		<Field.Field>
			<Field.Label for="bulk-node">{m.reprocess_from()}</Field.Label>
			<Select id="bulk-node" bind:value={fromNode} options={nodes} />
		</Field.Field>
		{#if asksModel && count > WARN_ABOVE}
			<p class="text-sm text-lane-yellow-foreground">
				{m.bulk_reprocess_model({ calls: formatNumber(count * MODEL_CALLS) })}
			</p>
		{/if}
		{#if fromNode === 'ocr'}
			<p class="text-sm text-muted-foreground">{m.bulk_reprocess_vision()}</p>
		{/if}
	</FormDialog>
{/if}

<ConfirmDialog
	bind:open={() => shown('delete'), showing('delete')}
	title={m.bulk_delete_title({ documents })}
	description={m.bulk_delete_hint()}
	confirmLabel={m.delete_title()}
	onconfirm={() => start({ kind: 'delete' })}
/>

<BulkSkipped operation={skipped} onclose={() => (skipped = null)} />
