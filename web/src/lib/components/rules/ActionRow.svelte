<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import MultiPicker from '#lib/components/MultiPicker.svelte';
	import Select from '#lib/components/Select.svelte';
	import { namedOptions, withChoice } from '#lib/components/rules/options.ts';
	import ValueInput from '#lib/components/rules/ValueInput.svelte';
	import TemplateInput from '#lib/components/templates/TemplateInput.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { ACTION_LABELS } from '#lib/rules/describe.ts';
	import ConditionGroup from '#lib/components/rules/ConditionGroup.svelte';
	import { Input } from '#lib/components/ui/input/index.ts';
	import {
		MISSING,
		defaultValue,
		type ActionNode,
		type Missing,
		type RuleModel
	} from '#lib/rules/model.ts';
	import { session } from '#lib/session.svelte.ts';
	import { tagOptions } from '#lib/tags.ts';

	// One step: an action, a step that asks a webhook, or a condition. `targets` are where the
	// rule may file: the spaces whoever saves it edits, and other users' personal spaces
	// (handing the document over). `onunreadable` says while the value's text cannot be read
	// (see `ValueInput`). A condition step edits its conditions in `model` (the limits are the
	// rule's), with `errors` by key; `steps` are the names of the steps before that ask.
	let {
		action,
		lookup,
		targets,
		error,
		model = null,
		errors = {},
		steps = [],
		onremove,
		onup,
		ondown,
		onunreadable,
		onconditionunreadable
	}: {
		action: ActionNode;
		lookup: Lookup;
		targets: readonly { value: string; label: string }[];
		error?: string;
		model?: RuleModel | null;
		errors?: Record<string, string>;
		steps?: readonly string[];
		onunreadable?: (unreadable: boolean) => void;
		onconditionunreadable?: (key: string, unreadable: boolean) => void;
		onremove: () => void;
		onup?: () => void;
		ondown?: () => void;
	} = $props();

	const invalid = $derived(Boolean(error));
	const label = $derived(ACTION_LABELS[action.type]());

	// A space the rule files into that the caller may not file into (another editor saved it,
	// into a space the caller is no member of): kept, but saving needs another choice.
	const unreachable = $derived(
		action.type === 'set_space' &&
			action.space_id !== '' &&
			!targets.some((entry) => entry.value === action.space_id)
	);

	// A rule sends only through the webhooks of whoever saves it.
	const webhooks = $derived(
		(lookup.webhooks ?? [])
			.filter((webhook) => webhook.owner_id === session.user?.id)
			.map((webhook) => ({ value: webhook.id, label: webhook.name }))
	);

	const field = $derived(
		action.type === 'set_field'
			? (lookup.fields.find((entry) => entry.id === action.field_id) ?? null)
			: null
	);

	const MISSING_LABELS: Record<Missing, () => string> = {
		red: m.rule_missing_red,
		yellow: m.rule_missing_yellow,
		continue: m.rule_missing_continue
	};
	const missingOptions = MISSING.map((value) => ({ value, label: MISSING_LABELS[value]() }));
</script>

<div class="flex flex-col gap-2 rounded-xl border bg-background p-3" data-key={action.key}>
	<div class="flex flex-wrap items-start gap-2">
		<span class="w-full pt-2 text-sm font-medium sm:w-44">{label}</span>
		<div class="flex min-w-0 flex-1 basis-64 flex-col gap-2">
			{#if action.type === 'set_space'}
				<Select
					aria-label={label}
					aria-invalid={invalid || undefined}
					bind:value={action.space_id}
					options={withChoice(targets, action.space_id, m.rule_space_unreachable())}
					class="h-10"
				/>
				{#if unreachable}
					<p class="text-sm text-muted-foreground">{m.rule_space_unreachable_hint()}</p>
				{/if}
			{:else if action.type === 'set_contact'}
				<Select
					aria-label={label}
					aria-invalid={invalid || undefined}
					bind:value={action.contact_id}
					options={withChoice(namedOptions(lookup.contacts), action.contact_id)}
					class="h-10"
				/>
			{:else if action.type === 'set_document_type'}
				<Select
					aria-label={label}
					aria-invalid={invalid || undefined}
					bind:value={action.document_type_id}
					options={withChoice(namedOptions(lookup.documentTypes), action.document_type_id)}
					class="h-10"
				/>
			{:else if action.type === 'set_topic'}
				<Select
					aria-label={label}
					aria-invalid={invalid || undefined}
					bind:value={action.topic_id}
					options={withChoice(tagOptions(lookup.tags, 'topic'), action.topic_id)}
					class="h-10"
				/>
			{:else if action.type === 'set_title'}
				<TemplateInput
					id="title-{action.key}"
					{label}
					{invalid}
					fields={lookup.fields}
					bind:value={action.template}
				/>
			{:else if action.type === 'add_tags' || action.type === 'remove_tags'}
				<MultiPicker
					{label}
					{invalid}
					options={tagOptions(lookup.tags, 'document')}
					selected={action.tag_ids}
					onchange={(next) => {
						if (action.type === 'add_tags' || action.type === 'remove_tags') action.tag_ids = next;
					}}
				/>
			{:else if action.type === 'set_field'}
				<Select
					aria-label={m.rule_condition_field()}
					aria-invalid={(invalid && !action.field_id) || undefined}
					value={action.field_id}
					options={withChoice(namedOptions(lookup.fields), action.field_id)}
					onchange={(id) => {
						if (action.type !== 'set_field') return;
						const chosen = lookup.fields.find((entry) => entry.id === id) ?? null;
						action.field_id = id;
						action.value = (defaultValue('field', 'is', chosen) ?? '') as typeof action.value;
					}}
					class="h-10"
				/>
				{#if action.field_id}
					<ValueInput
						{field}
						{invalid}
						template
						fields={lookup.fields}
						id="value-{action.key}"
						label={m.rule_condition_value()}
						value={action.value}
						onchange={(next) => {
							if (action.type === 'set_field') action.value = next as typeof action.value;
						}}
						{onunreadable}
					/>
				{/if}
			{:else if action.type === 'force_review'}
				<TemplateInput
					id="reason-{action.key}"
					label={m.rule_review_reason()}
					{invalid}
					fields={lookup.fields}
					bind:value={action.reason}
				/>
			{:else if action.type === 'ask_webhook'}
				<div class="grid gap-3 sm:grid-cols-2">
					<Field.Field>
						<Field.Label for="ask-name-{action.key}">{m.rule_ask_name()}</Field.Label>
						<Input
							id="ask-name-{action.key}"
							class="font-mono"
							maxlength={50}
							aria-invalid={invalid || undefined}
							bind:value={action.name}
						/>
					</Field.Field>
					<Field.Field>
						<Field.Label for="ask-webhook-{action.key}">{m.rule_ask_webhook()}</Field.Label>
						<Select
							id="ask-webhook-{action.key}"
							aria-invalid={(invalid && !action.webhook_id) || undefined}
							bind:value={action.webhook_id}
							options={withChoice(webhooks, action.webhook_id, m.rule_webhook_unknown())}
							class="h-10"
						/>
					</Field.Field>
					<Field.Field>
						<Field.Label for="ask-timeout-{action.key}">{m.rule_ask_timeout()}</Field.Label>
						<Input
							id="ask-timeout-{action.key}"
							type="number"
							min={0.5}
							max={1440}
							step={0.5}
							value={String(action.timeout_seconds / 60)}
							oninput={(event) => {
								if (action.type === 'ask_webhook') {
									action.timeout_seconds = Math.round(Number(event.currentTarget.value) * 60);
								}
							}}
						/>
					</Field.Field>
					<Field.Field>
						<Field.Label for="ask-missing-{action.key}">{m.rule_ask_missing()}</Field.Label>
						<Select
							id="ask-missing-{action.key}"
							value={action.missing}
							options={missingOptions}
							onchange={(next) => {
								if (action.type === 'ask_webhook') action.missing = next as Missing;
							}}
							class="h-10"
						/>
					</Field.Field>
				</div>
				<p class="text-sm text-muted-foreground">{m.rule_ask_name_hint()}</p>
				<p class="text-sm text-muted-foreground">
					{webhooks.length ? m.rule_ask_hint() : m.rule_send_webhook_none()}
				</p>
			{:else if action.type === 'condition' && model}
				<ConditionGroup
					group={action.conditions}
					{model}
					{lookup}
					{errors}
					{steps}
					top
					onunreadable={onconditionunreadable}
				/>
				<p class="text-sm text-muted-foreground">{m.rule_condition_step_hint()}</p>
			{:else if action.type === 'send_webhook'}
				<Select
					aria-label={label}
					aria-invalid={invalid || undefined}
					bind:value={action.webhook_id}
					options={withChoice(webhooks, action.webhook_id, m.rule_webhook_unknown())}
					class="h-10"
				/>
				<p class="text-sm text-muted-foreground">
					{webhooks.length ? m.rule_send_webhook_hint() : m.rule_send_webhook_none()}
				</p>
			{/if}
		</div>
		<div class="flex gap-0.5">
			<Button
				variant="ghost"
				size="icon"
				aria-label={m.rule_move_up()}
				disabled={!onup}
				onclick={() => onup?.()}
			>
				<ArrowUp aria-hidden="true" />
			</Button>
			<Button
				variant="ghost"
				size="icon"
				aria-label={m.rule_move_down()}
				disabled={!ondown}
				onclick={() => ondown?.()}
			>
				<ArrowDown aria-hidden="true" />
			</Button>
			<Button variant="ghost" size="icon" aria-label={m.rule_remove()} onclick={onremove}>
				<Trash2 aria-hidden="true" />
			</Button>
		</div>
	</div>
	{#if error}<Field.Error>{error}</Field.Error>{/if}
</div>
