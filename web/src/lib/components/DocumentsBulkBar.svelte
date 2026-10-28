<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ListChecks from '@lucide/svelte/icons/list-checks';
	import X from '@lucide/svelte/icons/x';
	import type { components } from '#lib/api/schema.ts';
	import IconButton from '#lib/components/IconButton.svelte';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import SearchSelect from '#lib/components/SearchSelect.svelte';
	import Select from '#lib/components/Select.svelte';
	import SelectionBar from '#lib/components/SelectionBar.svelte';
	import TagPicker from '#lib/components/TagPicker.svelte';
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
	import { bulkDocuments, MODEL_CALLS, WARN_ABOVE } from '#lib/bulk.ts';
	import {
		type BulkAction,
		type BulkOperation,
		type BulkRun,
		type BulkSelection
	} from '#lib/bulk.svelte.ts';

	type ReprocessNode = components['schemas']['ReprocessNode'];

	// The bar of the selection mode of the documents list (web/DESIGN.md, "Choosing many"): an
	// X that ends the mode, "Auswählen" (a menu: this page, all N hits, none, end the mode), how
	// many are chosen, and the actions, pale while none is (Tags, Kontakt, Typ, and under "Mehr"
	// Thema, Space, Bestätigen, Neu verarbeiten, Löschen). Each action but confirming opens its
	// dialog; deleting and reprocessing name the exact count. The action runs in the background
	// (`run`, owned by the page: the bar is rendered anew across the phone width): the bar shows
	// how far it has come in place of its actions.
	let {
		count,
		all,
		offerAll,
		limit,
		capped,
		selection,
		run,
		lookup,
		onpage,
		onall,
		onclear,
		onend
	}: {
		/** How many documents are chosen. */
		count: number;
		/** Every hit of the search and filters is chosen, not ids. */
		all: boolean;
		/** The hits to offer "Alle N Treffer auswählen" for (more than the page shows). */
		offerAll: number | null;
		/** More hits than one action takes: the most it takes. */
		limit: number | null;
		/** The search reaches fewer hits than it found. */
		capped: number | null;
		selection: () => BulkSelection;
		/** The action on the choice as the page follows it. */
		run: BulkRun;
		lookup: Lookup | null;
		onpage: () => void;
		onall: () => void;
		/** Choose none. */
		onclear: () => void;
		/** End the selection mode. */
		onend: () => void;
	} = $props();

	const running = $derived(run.operation);

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

	/** Start `action` on the selection; the page follows it until it ends. */
	async function start(action: BulkAction) {
		await run.start(selection(), action);
		dialog = null;
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

<!-- Before the count: the X that ends the mode and, on a desktop, the chooser. -->
{#snippet lead()}
	<IconButton label={m.bulk_mode_end()} onclick={onend}>
		<X aria-hidden="true" />
	</IconButton>
	{#if !phone.current}{@render chooser()}{/if}
{/snippet}

<!-- How far the action has come, in place of the hint and the actions. -->
{#snippet progress(operation: BulkOperation)}
	{@const running = m.bulk_running({
		done: formatNumber(operation.done),
		total: formatNumber(operation.total)
	})}
	<span class="flex min-w-0 items-center gap-3">
		<Progress
			value={operation.done}
			max={Math.max(operation.total, 1)}
			class="max-w-48"
			aria-label={running}
		/>
		<span aria-live="polite">{running}</span>
	</span>
{/snippet}

<!-- How far the choice reaches, in words. -->
{#snippet reach()}
	{#if all && capped !== null}
		{m.bulk_all_hits_capped({ count: formatNumber(capped) })}
	{:else if all}
		{m.bulk_all_hits()}
	{:else if count === 0}
		{m.bulk_tap_hint()}
	{:else if limit !== null}
		{m.bulk_limit({ max: formatNumber(limit) })}
	{/if}
{/snippet}

{#snippet actions()}
	<Button variant="outline" size="sm" disabled={count === 0} onclick={open('tags')}>
		{m.field_tags()}
	</Button>
	<Button variant="outline" size="sm" disabled={count === 0} onclick={open('contact')}>
		{m.field_contact()}
	</Button>
	<Button variant="outline" size="sm" disabled={count === 0} onclick={open('type')}>
		{m.bulk_type()}
	</Button>
	<DropdownMenu.Root>
		<DropdownMenu.Trigger disabled={count === 0}>
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
{/snippet}

{#snippet progressHint()}
	{#if running}{@render progress(running)}{/if}
{/snippet}

<SelectionBar
	count={m.selection_selected({ count: formatNumber(count) })}
	busy={run.busy}
	{lead}
	trail={phone.current && !running ? chooser : undefined}
	hint={running ? progressHint : all || count === 0 || limit !== null ? reach : undefined}
	actions={running ? undefined : actions}
/>

<!-- What to choose at once: the page, every hit, none; and the end of the mode. -->
{#snippet chooser()}
	<DropdownMenu.Root>
		<DropdownMenu.Trigger disabled={running !== null}>
			{#snippet child({ props })}
				<Button {...props} variant="outline" size="sm">
					<ListChecks aria-hidden="true" />
					{m.bulk_mode()}
					<ChevronDown aria-hidden="true" />
				</Button>
			{/snippet}
		</DropdownMenu.Trigger>
		<DropdownMenu.Content align={phone.current ? 'end' : 'start'} class="w-64">
			<DropdownMenu.Item onSelect={onpage}>{m.bulk_select_page()}</DropdownMenu.Item>
			{#if offerAll !== null}
				<DropdownMenu.Item onSelect={onall}>
					{m.bulk_select_all({ count: formatNumber(offerAll) })}
				</DropdownMenu.Item>
			{/if}
			<DropdownMenu.Item disabled={count === 0} onSelect={onclear}>
				{m.bulk_select_none()}
			</DropdownMenu.Item>
			<DropdownMenu.Separator />
			<DropdownMenu.Item onSelect={onend}>{m.bulk_mode_end()}</DropdownMenu.Item>
		</DropdownMenu.Content>
	</DropdownMenu.Root>
{/snippet}

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
