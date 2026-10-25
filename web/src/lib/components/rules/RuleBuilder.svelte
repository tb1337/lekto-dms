<script lang="ts">
	import Select from '#lib/components/Select.svelte';
	import ActionRow from '#lib/components/rules/ActionRow.svelte';
	import ConditionGroup from '#lib/components/rules/ConditionGroup.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { ACTION_LABELS, TRIGGER_LABELS } from '#lib/rules/describe.ts';
	import {
		ACTION_TYPES,
		LIMITS,
		TRIGGERS,
		asksBefore,
		move,
		newAction,
		type ActionType,
		type RuleModel
	} from '#lib/rules/model.ts';

	// The form of a rule: name, priority, when it runs, its conditions and actions. The page
	// saves it; `errors` are by key (see `validate` and `saveErrors`). It does not save while a
	// period's text cannot be read (`unreadable`, by key): the model then is not what is shown.
	let {
		model,
		place = '',
		places = [],
		onplace,
		placeHint,
		lookup,
		targets,
		errors,
		general,
		busy,
		cancelHref,
		onsubmit
	}: {
		model: RuleModel;
		/** Where the rule belongs: `global` or a space; editing it may move it. */
		place?: string;
		/** The places to choose from; fewer than two: no choice. */
		places?: readonly { value: string; label: string }[];
		onplace?: (place: string) => void;
		/** Said under the choice of the place besides what a place is (editing: who moves it). */
		placeHint?: string;
		lookup: Lookup;
		/** Where the rule may file documents (spaces, hand-overs). */
		targets: readonly { value: string; label: string }[];
		errors: Record<string, string>;
		general: string | null;
		busy: boolean;
		cancelHref: string;
		onsubmit: () => void;
	} = $props();

	const addable = $derived([
		{ value: '', label: m.rule_add_action() },
		...ACTION_TYPES.map((type) => ({ value: type, label: ACTION_LABELS[type]() }))
	]);
	let adding = $state('');
	const asks = $derived(model.actions.some((action) => action.type === 'ask_webhook'));
	let unreadable = $state<Record<string, boolean>>({});
	const blocked = $derived(Object.values(unreadable).some(Boolean));

	function mark(key: string, cannotRead: boolean) {
		unreadable[key] = cannotRead;
	}

	function add(type: string) {
		if (type) model.actions.push(newAction(type as ActionType));
		adding = '';
	}

	function toggleTrigger(trigger: (typeof TRIGGERS)[number], on: boolean) {
		model.triggers = on
			? [...model.triggers, trigger]
			: model.triggers.filter((entry) => entry !== trigger);
	}
</script>

<form
	class="flex flex-col gap-6"
	novalidate
	onsubmit={(event) => {
		event.preventDefault();
		if (blocked) return;
		onsubmit();
	}}
>
	<div class="grid gap-4 sm:grid-cols-[1fr_12rem]">
		<Field.Field>
			<Field.Label for="rule-name">{m.field_name()}</Field.Label>
			<Input
				id="rule-name"
				bind:value={model.name}
				maxlength={LIMITS.name}
				aria-invalid={errors.name ? true : undefined}
			/>
			{#if errors.name}<Field.Error>{errors.name}</Field.Error>{/if}
		</Field.Field>
		<Field.Field>
			<Field.Label for="rule-priority">{m.rule_priority()}</Field.Label>
			<Input
				id="rule-priority"
				type="number"
				min={LIMITS.priorityMin}
				max={LIMITS.priorityMax}
				step={1}
				bind:value={model.priority}
				aria-invalid={errors.priority ? true : undefined}
			/>
			<Field.Description>{m.rule_priority_hint()}</Field.Description>
			{#if errors.priority}<Field.Error>{errors.priority}</Field.Error>{/if}
		</Field.Field>
	</div>

	{#if places.length > 1}
		<Field.Field>
			<Field.Label for="rule-scope">{m.rule_scope()}</Field.Label>
			<Select
				id="rule-scope"
				value={place}
				options={places}
				onchange={(value) => onplace?.(value)}
			/>
			<Field.Description>{m.rule_scope_hint()}</Field.Description>
			{#if placeHint}<Field.Description>{placeHint}</Field.Description>{/if}
		</Field.Field>
	{/if}

	<fieldset class="flex flex-col gap-2">
		<legend class="mb-2 text-sm font-medium">{m.rule_triggers()}</legend>
		{#each TRIGGERS as trigger (trigger)}
			<label class="flex items-center gap-2 text-sm">
				<input
					type="checkbox"
					class="size-4 accent-primary"
					checked={model.triggers.includes(trigger)}
					onchange={(event) => toggleTrigger(trigger, event.currentTarget.checked)}
				/>
				{TRIGGER_LABELS[trigger]()}
			</label>
		{/each}
		{#if asks}<p class="text-sm text-muted-foreground">{m.rule_triggers_ask_hint()}</p>{/if}
		{#if errors.triggers}<Field.Error>{errors.triggers}</Field.Error>{/if}
	</fieldset>

	<section class="flex flex-col gap-3" aria-labelledby="rule-conditions">
		<h2 id="rule-conditions" class="text-lg font-semibold">{m.rule_conditions()}</h2>
		<ConditionGroup group={model.conditions} {model} {lookup} {errors} onunreadable={mark} />
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="rule-actions">
		<h2 id="rule-actions" class="text-lg font-semibold">{m.rule_actions()}</h2>
		{#each model.actions as action, index (action.key)}
			<ActionRow
				{action}
				{lookup}
				{targets}
				{model}
				{errors}
				steps={asksBefore(model, index)}
				error={errors[action.key]}
				onunreadable={(unreadable) => mark(action.key, unreadable)}
				onconditionunreadable={mark}
				onremove={() => model.actions.splice(index, 1)}
				onup={index > 0 ? () => move(model.actions, index, -1) : undefined}
				ondown={index < model.actions.length - 1 ? () => move(model.actions, index, 1) : undefined}
			/>
		{/each}
		<Select
			aria-label={m.rule_add_action()}
			bind:value={adding}
			options={addable}
			disabled={model.actions.length >= LIMITS.actions}
			onchange={add}
			class="h-10 w-full sm:w-72"
		/>
		{#if errors.actions}<Field.Error>{errors.actions}</Field.Error>{/if}
	</section>

	<div class="flex flex-col gap-3 border-t pt-4">
		{#if general}<Field.Error>{general}</Field.Error>{/if}
		<p class="text-sm text-muted-foreground">{m.rule_save_hint()}</p>
		<div class="flex flex-wrap gap-2">
			<Button type="submit" disabled={busy || blocked}>{m.rule_save()}</Button>
			<a href={cancelHref} class="inline-flex h-9 items-center px-3 text-sm hover:underline">
				{m.cancel()}
			</a>
		</div>
	</div>
</form>
