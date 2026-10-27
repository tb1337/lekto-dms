<script lang="ts">
	import { untrack } from 'svelte';
	import Workflow from '@lucide/svelte/icons/workflow';
	import { api } from '#lib/api/client.ts';
	import AssignmentList, { type Assignment } from '#lib/components/AssignmentList.svelte';
	import ColorPicker from '#lib/components/ColorPicker.svelte';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import ChipInput from '#lib/components/ChipInput.svelte';
	import ContactLogoEditor from '#lib/components/ContactLogoEditor.svelte';
	import IconPicker from '#lib/components/IconPicker.svelte';
	import EditorShell from '#lib/components/EditorShell.svelte';
	import HintLabel from '#lib/components/HintLabel.svelte';
	import InfoHint from '#lib/components/InfoHint.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import TagPicker from '#lib/components/TagPicker.svelte';
	import Select from '#lib/components/Select.svelte';
	import IdentifiersEditor from '#lib/components/IdentifiersEditor.svelte';
	import TemplateInput from '#lib/components/templates/TemplateInput.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { changesOf, type IdentifierRow, refusedRow, rowsOf } from '#lib/identifiers.ts';
	import { latest } from '#lib/latest.ts';
	import { type Extra, type Item, type Values } from '#lib/masterdata-api.ts';
	import type {
		Contact,
		FieldDefinition,
		Tag,
		TagScope,
		UserName
	} from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { below, ofScope, pathLabel } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';
	import { Choice, ChoiceBox } from '#lib/components/ui/choice/index.ts';

	/** The kinds of tag a new one can be, each with an example. */
	const KIND_CARDS: { scope: TagScope; title: () => string; example: () => string }[] = [
		{ scope: 'document', title: m.tag_kind_document, example: m.tag_kind_document_example },
		{ scope: 'contact', title: m.tag_kind_contact, example: m.tag_kind_contact_example },
		{ scope: 'document_type', title: m.tag_kind_type, example: m.tag_kind_type_example },
		{ scope: 'topic', title: m.tag_kind_topic, example: m.tag_kind_topic_example }
	];

	// Create or change a contact (name, logo, aliases, groups, topics, identifiers with their
	// topic), a document type (name, icon, description, title pattern, fields, groups) or a tag
	// (name, parent of its scope, icon, colour, how it is set, whether documents show it; a new
	// one without a scope asks for its kind first, `chooseScope`). The
	// API decides what is valid; its answer (e.g. 409 for a taken name) shows above the body. A
	// contact's logo is saved apart, at once (`ContactLogoEditor`). An item that exists can be
	// deleted from here (`ondelete`).
	let {
		open = $bindable(false),
		title,
		shortTitle = title,
		extra,
		initial = null,
		presetName = '',
		submitLabel = m.save(),
		ruleHref = null,
		fields = null,
		tags = [],
		scope = null,
		chooseScope = false,
		fetching = false,
		onlogo = () => {},
		ontagcreated = () => {},
		onsubmit,
		ondelete,
		deleteDescription = ''
	}: {
		open?: boolean;
		title: string;
		/** The title in the bar of a phone. */
		shortTitle?: string;
		extra: Extra;
		initial?: Item | null;
		/** A new item's name, filled in. */
		presetName?: string;
		submitLabel?: string;
		/** The rule of the type's title pattern, to go to from here. */
		ruleHref?: string | null;
		/** Every field, for a document type's: those of the type are assigned there. */
		fields?: readonly FieldDefinition[] | null;
		/** Every tag: parents of a tag, groups of a contact or type, topics of a contact. */
		tags?: readonly Tag[];
		/** The scope of a tag. */
		scope?: TagScope | null;
		/** A new tag whose kind is chosen here first (`scope` is null). */
		chooseScope?: boolean;
		/** The server fetches logos of contacts from their websites. */
		fetching?: boolean;
		/** A contact's logo changed (saved at once). */
		onlogo?: () => void;
		/** A picker made a tag (a group, a topic): `tags` should hold it. */
		ontagcreated?: (tag: Tag) => void;
		onsubmit: (values: Values) => Promise<void>;
		/** Deletes the item (asked first); its answer (409: still in use) shows as a toast. */
		ondelete?: () => Promise<void>;
		/** When deleting is possible. */
		deleteDescription?: string;
	} = $props();

	// Ids of this dialog's fields: a second one may stand over it (a tag made from a picker).
	const uid = $props.id();
	let name = $state('');
	let aliases = $state<string[]>([]);
	let identifiers = $state<IdentifierRow[]>([]);
	let description = $state('');
	let titlePattern = $state('');
	let relationTarget = $state(false);
	let assigned = $state<Assignment[]>([]);
	let groupIds = $state<string[]>([]);
	let topicIds = $state<string[]>([]);
	let parentId = $state('');
	let manual = $state(false);
	let shown = $state(true);
	let icon = $state<string | null>(null);
	let color = $state<string | null>(null);
	// A tag's scope: as given, or as chosen for a new one.
	let kind = $state<TagScope | null>(null);
	const groupScope = $derived<TagScope | null>(
		extra === 'aliases' ? 'contact' : extra === 'description' ? 'document_type' : null
	);
	const isGroup = $derived(kind === 'contact' || kind === 'document_type');
	const isTopic = $derived(kind === 'topic');
	// The topics a contact enables; its identifiers point to one of them.
	const enabledTopics = $derived(
		ofScope(tags, 'topic').filter((topic) => topicIds.includes(topic.id))
	);
	// A tag goes under one of its scope, never under itself or one below it.
	const parents = $derived.by(() => {
		if (kind === null) return [];
		const own = initial?.id;
		const excluded = own ? below(tags, own).add(own) : new Set<string>();
		return ofScope(tags, kind)
			.filter((tag) => !excluded.has(tag.id))
			.map((tag) => ({ value: tag.id, label: pathLabel(tag) }));
	});
	const typed = $derived((fields ?? []).filter((field) => field.document_type_ids !== null));
	const everywhere = $derived((fields ?? []).filter((field) => field.document_type_ids === null));
	// A contact and a document type are long: their identifiers or fields stand in a tab of
	// their own (Tobi, 20.10.2026); a tag's editor is short and has none.
	let tab = $state('general');
	// The identifier line that is open, and what the API said about one (it quotes the value it
	// refuses): saving then opens its tab and its line.
	let openedIdentifier = $state<number | null>(null);
	let identifierErrors = $state<Record<number, string>>({});
	// The users a customer or personnel number may belong to: fetched once each time the dialog
	// opens for a contact, not on every switch to the identifiers tab. Without the list, a number
	// still shows whose it is by id.
	let users = $state<UserName[]>([]);
	const beginUsers = latest();
	$effect(() => {
		if (!open || extra !== 'aliases') return;
		const current = beginUsers();
		void api
			.GET('/api/v1/users')
			.then(({ data }) => {
				if (current() && Array.isArray(data)) users = data;
			})
			.catch(() => {});
	});
	const tabs = $derived.by(() => {
		const general = { value: 'general', label: m.master_tab_general() };
		if (extra === 'aliases') {
			return [
				general,
				{
					value: 'identifiers',
					label: m.master_identifiers(),
					count: identifiers.length,
					alert: Object.keys(identifierErrors).length > 0 ? m.editor_tab_problem() : undefined
				}
			];
		}
		if (extra === 'description' && fields) {
			return [general, { value: 'fields', label: m.master_type_fields(), count: assigned.length }];
		}
		return undefined;
	});
	const part = $derived(tabs ? tab : 'general');

	// The form starts from the item when the dialog opens or shows another one, never again
	// while it is open: the lists it is given change under it (a group made in a dialog over
	// this one loads the tags again), and what the person typed and chose stays.
	let filledFor: string | null = null;
	$effect(() => {
		const key = open ? (initial?.id ?? `new:${presetName}`) : null;
		if (key === filledFor) return;
		filledFor = key;
		if (key !== null) untrack(fill);
	});

	function fill() {
		tab = 'general';
		openedIdentifier = null;
		identifierErrors = {};
		name = initial?.name ?? presetName;
		aliases = [...(initial?.aliases ?? [])];
		identifiers = rowsOf(initial?.identifiers);
		description = initial?.description ?? '';
		titlePattern = initial?.title_pattern ?? '';
		relationTarget = initial?.relation_target ?? false;
		groupIds = [...(initial?.group_ids ?? [])];
		topicIds = [...(initial?.topic_ids ?? [])];
		kind = scope;
		parentId = initial?.parent_id ?? '';
		manual = initial?.assignment === 'manual';
		shown = initial?.shown ?? (scope === null || scope === 'document' || scope === 'topic');
		icon = initial?.icon ?? null;
		color = initial?.color ?? null;
		const id = initial?.id;
		assigned = id
			? typed
					.filter((field) => field.document_type_ids?.includes(id))
					.map((field) => ({
						id: field.id,
						required: field.required_document_type_ids.includes(id)
					}))
			: [];
	}

	/** A new tag becomes one of `next`: no parent yet, shown and set as that kind's are. */
	function chooseKind(next: TagScope) {
		kind = next;
		parentId = '';
		manual = false;
		shown = next === 'document' || next === 'topic';
	}

	/** Save; a refused identifier opens its tab and its line, the shell shows the error too. */
	async function submit() {
		identifierErrors = {};
		try {
			await onsubmit({
				name: name.trim(),
				aliases,
				...changesOf(identifiers, topicIds),
				description: description.trim() || null,
				title_pattern: titlePattern.trim() || null,
				relation_target: relationTarget,
				fields: extra === 'description' && fields ? assigned : null,
				group_ids: groupIds,
				topic_ids: topicIds,
				parent_id: parentId || null,
				assignment: manual ? 'manual' : 'auto',
				shown,
				icon,
				color,
				scope: kind
			});
		} catch (problem) {
			const refused = refusedRow(problem, identifiers);
			if (refused) {
				identifierErrors = { [refused.key]: describeError(problem) };
				openedIdentifier = refused.key;
				tab = 'identifiers';
			}
			throw problem;
		}
	}
</script>

{#snippet nameField()}
	<Field.Field>
		<Field.Label for="{uid}-name">{m.field_name()}</Field.Label>
		<Input id="{uid}-name" bind:value={name} maxlength={200} required />
	</Field.Field>
{/snippet}

<EditorShell
	bind:open
	{title}
	{shortTitle}
	{submitLabel}
	disabled={name.trim() === '' || (extra === 'tag' && kind === null)}
	action={submit}
	ondelete={initial && ondelete ? ondelete : undefined}
	deleteTitle={m.master_delete({ name: initial?.name ?? '' })}
	{deleteDescription}
	{tabs}
	bind:tab
	class={tabs ? 'h-[min(53.75rem,calc(100dvh-2rem))]' : undefined}
>
	{#if part === 'general'}
		{#if extra === 'tag' && chooseScope}
			<fieldset class="flex flex-col gap-2" aria-labelledby="{uid}-kind-label">
				<div class="mb-2 flex items-center gap-1">
					<span id="{uid}-kind-label" class="text-sm font-medium">{m.tag_kind()}</span>
					<InfoHint text={m.tag_kind_hint()} about={m.tag_kind()} />
				</div>
				<div class="grid gap-2 sm:grid-cols-2">
					{#each KIND_CARDS as card (card.scope)}
						<label
							class={cn(
								'flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors hover:bg-secondary/60',
								kind === card.scope && 'border-primary bg-primary/10 hover:bg-primary/10'
							)}
						>
							<ChoiceBox
								type="radio"
								name="{uid}-kind"
								value={card.scope}
								checked={kind === card.scope}
								onchange={() => chooseKind(card.scope)}
								class="mt-0.5"
							/>
							<span class="flex flex-col gap-0.5">
								<span class="text-sm font-medium">{card.title()}</span>
								<span class="text-sm text-muted-foreground">{card.example()}</span>
							</span>
						</label>
					{/each}
				</div>
			</fieldset>
		{/if}
		{#if extra !== 'tag' || kind !== null}
			{#if extra === 'aliases' && phone.current}
				<!-- On a phone the logo stands beside the name, what to do with it below. -->
				{#if initial}
					<ContactLogoEditor contact={initial as Contact} {fetching} onchanged={onlogo}>
						{#snippet beside()}{@render nameField()}{/snippet}
					</ContactLogoEditor>
				{:else}
					<div class="flex flex-col gap-2" data-logo-beside>
						<div class="flex items-center gap-3">
							<ContactAvatar contact={{ name }} size="xl" />
							<div class="min-w-0 flex-1">{@render nameField()}</div>
						</div>
						<p class="pl-17 text-xs text-muted-foreground">{m.logo_after_create()}</p>
					</div>
				{/if}
			{:else}
				{@render nameField()}
			{/if}
		{/if}
		{#if extra === 'aliases' && !phone.current}
			<Field.Field>
				<Field.Label>{m.logo_title()}</Field.Label>
				{#if initial}
					<ContactLogoEditor contact={initial as Contact} {fetching} onchanged={onlogo} />
				{:else}
					<Field.Description>{m.logo_after_create()}</Field.Description>
				{/if}
			</Field.Field>
		{/if}
		{#if extra === 'description'}{@render iconField()}{/if}
		{#if extra === 'tag' && kind !== null}
			<Field.Field>
				<Field.Label for="{uid}-parent">
					{isGroup ? m.tag_parent_group() : isTopic ? m.topic_parent() : m.tag_parent()}
				</Field.Label>
				<Select
					id="{uid}-parent"
					bind:value={parentId}
					options={[
						{
							value: '',
							label: isGroup
								? m.tag_parent_group_none()
								: isTopic
									? m.topic_parent_none()
									: m.tag_parent_none()
						},
						...parents
					]}
					class="h-10"
				/>
			</Field.Field>
			{@render iconField()}
			<Field.Field>
				<Field.Label id="{uid}-color-label">{m.master_color()}</Field.Label>
				<ColorPicker id="{uid}-color" bind:value={color} />
			</Field.Field>
			{#if !isGroup}
				<fieldset class="flex flex-col gap-2" aria-labelledby="{uid}-assignment-label">
					<div class="mb-2 flex items-center gap-1">
						<span id="{uid}-assignment-label" class="text-sm font-medium">
							{m.tag_assignment()}
						</span>
						<InfoHint
							text={isTopic ? m.topic_assignment_hint() : m.tag_assignment_hint()}
							about={m.tag_assignment()}
						/>
					</div>
					<div class="flex flex-wrap gap-x-6 gap-y-2">
						<Choice type="radio" name="{uid}-assignment" value={false} bind:group={manual}>
							{m.tag_assignment_auto()}
						</Choice>
						<Choice type="radio" name="{uid}-assignment" value={true} bind:group={manual}>
							{m.tag_assignment_manual()}
						</Choice>
					</div>
				</fieldset>
			{/if}
			<div class="flex items-center gap-1">
				<Choice bind:checked={shown} aria-describedby="{uid}-shown-hint" class="font-medium">
					{m.tag_shown()}
				</Choice>
				<InfoHint
					text={isGroup
						? m.tag_group_shown_hint()
						: isTopic
							? m.topic_shown_hint()
							: m.tag_shown_hint()}
					about={m.tag_shown()}
					id="{uid}-shown-hint"
				/>
			</div>
			<div
				class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-muted/60 px-3 py-2.5 text-sm text-muted-foreground"
			>
				{m.master_color_preview()}
				<TagChip
					tag={{
						id: initial?.id ?? 'new',
						name: name.trim() || m.field_name(),
						path: [name.trim() || m.field_name()],
						icon,
						color
					}}
					topic={isTopic}
					group={isGroup}
					size="md"
				/>
				<span class="text-xs">
					{isTopic
						? m.tag_preview_topic()
						: isGroup
							? m.tag_preview_group()
							: m.tag_preview_document()}
				</span>
			</div>
		{/if}
		{#if groupScope !== null}
			<Field.Field>
				<HintLabel
					id="{uid}-groups-label"
					label={m.master_groups()}
					hint={groupScope === 'contact'
						? m.master_contact_groups_hint()
						: m.master_type_groups_hint()}
				/>
				<TagPicker
					id="{uid}-groups"
					label={m.master_groups()}
					labelledby="{uid}-groups-label"
					title={groupScope === 'contact' ? m.master_contact_groups() : m.master_type_groups()}
					scope={groupScope}
					{tags}
					selected={groupIds}
					onchange={(next) => (groupIds = next)}
					oncreated={ontagcreated}
				/>
			</Field.Field>
		{/if}
		{#if extra === 'aliases'}
			<Field.Field>
				<HintLabel
					id="{uid}-topics-label"
					label={m.master_topics()}
					hint={m.master_contact_topics_hint()}
				/>
				<TagPicker
					id="{uid}-topics"
					label={m.master_topics()}
					labelledby="{uid}-topics-label"
					title={m.master_topics()}
					scope="topic"
					{tags}
					selected={topicIds}
					onchange={(next) => (topicIds = next)}
					oncreated={ontagcreated}
				/>
			</Field.Field>
			<Field.Field>
				<HintLabel
					id="{uid}-aliases-label"
					label={m.master_aliases()}
					hint={m.master_aliases_hint()}
					hintId="{uid}-aliases-hint"
				/>
				<ChipInput
					bind:values={aliases}
					labelledby="{uid}-aliases-label"
					describedby="{uid}-aliases-hint"
					addLabel={m.alias_add()}
					inputLabel={m.alias_input()}
				/>
			</Field.Field>
		{:else if extra === 'description'}
			<Field.Field>
				<HintLabel
					for="{uid}-description"
					label={m.master_description()}
					hint={m.master_description_hint()}
					hintId="{uid}-description-hint"
				/>
				<Textarea
					id="{uid}-description"
					bind:value={description}
					rows={3}
					maxlength={300}
					aria-describedby="{uid}-description-hint"
				/>
			</Field.Field>
			<Field.Field>
				<HintLabel
					for="{uid}-title-pattern"
					label={m.master_title_pattern()}
					hint={m.master_title_pattern_hint()}
				/>
				<TemplateInput
					id="{uid}-title-pattern"
					bind:value={titlePattern}
					label={m.master_title_pattern()}
					documentType={initial?.id ?? null}
					extraFields={initial ? [] : assigned.map((item) => item.id)}
				/>
				{#if ruleHref}
					<a
						href={ruleHref}
						class="inline-flex items-center gap-1 self-start text-sm text-brand hover:underline"
						onclick={() => (open = false)}
					>
						<Workflow class="size-3.5" aria-hidden="true" />
						{m.master_title_rule()}
					</a>
				{/if}
			</Field.Field>
			<div class="flex items-center gap-1">
				<Choice
					bind:checked={relationTarget}
					aria-describedby="{uid}-relation-target-hint"
					class="font-medium"
				>
					{m.master_relation_target()}
				</Choice>
				<InfoHint
					text={m.master_relation_target_hint()}
					about={m.master_relation_target()}
					id="{uid}-relation-target-hint"
				/>
			</div>
		{/if}
	{/if}
	{#if part === 'identifiers'}
		<IdentifiersEditor
			bind:rows={identifiers}
			bind:opened={openedIdentifier}
			topics={enabledTopics}
			errors={identifierErrors}
			hint={m.master_identifiers_hint()}
			{users}
		/>
	{:else if part === 'fields'}
		{#if fields}
			<Field.Field>
				<AssignmentList
					{assigned}
					candidates={typed.map((field) => ({
						id: field.id,
						name: field.name,
						hint: `field.${field.key}`
					}))}
					label={m.master_type_fields()}
					addLabel={m.master_type_add_field()}
					emptyLabel={m.master_type_no_fields()}
					onchange={(items) => (assigned = items)}
				/>
				{#if everywhere.length > 0}
					<Field.Description>
						{m.master_type_global_fields({
							fields: everywhere.map((field) => field.name).join(', ')
						})}
					</Field.Description>
				{/if}
			</Field.Field>
		{/if}
	{/if}
</EditorShell>

{#snippet iconField()}
	<Field.Field>
		<HintLabel id="{uid}-icon-label" label={m.master_icon()} hint={m.master_icon_hint()} />
		<IconPicker id="{uid}-icon" bind:value={icon} />
	</Field.Field>
{/snippet}
