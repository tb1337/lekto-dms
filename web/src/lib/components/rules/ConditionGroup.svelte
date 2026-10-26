<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import ListPlus from '@lucide/svelte/icons/list-plus';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Select from '#lib/components/Select.svelte';
	import ConditionGroup from '#lib/components/rules/ConditionGroup.svelte';
	import ConditionRow from '#lib/components/rules/ConditionRow.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import {
		canAddCondition,
		canAddGroup,
		move,
		newCondition,
		newGroup,
		type GroupNode,
		type RuleModel
	} from '#lib/rules/model.ts';
	import { cn } from '#lib/utils.ts';
	import { Choice } from '#lib/components/ui/choice/index.ts';

	// A group of conditions: and/or, turned around or not, with conditions and subgroups.
	// `onunreadable` says, by the condition's key, while a value's text cannot be read.
	// `steps`: in a condition step, the names of the steps before that ask (its conditions may
	// look at their answers); `top`: the group is a step's own, not a subgroup.
	let {
		group,
		model,
		lookup,
		errors,
		steps = null,
		top = false,
		onremove,
		onup,
		ondown,
		onunreadable
	}: {
		group: GroupNode;
		model: RuleModel;
		lookup: Lookup;
		errors: Record<string, string>;
		steps?: readonly string[] | null;
		top?: boolean;
		onunreadable?: (key: string, unreadable: boolean) => void;
		onremove?: () => void;
		onup?: () => void;
		ondown?: () => void;
	} = $props();

	const root = $derived(top || group.key === model.conditions.key);
	const modes = [
		{ value: 'all', label: m.rule_mode_all() },
		{ value: 'any', label: m.rule_mode_any() }
	];
	const error = $derived(errors[group.key]);

	const remove = (index: number) => group.items.splice(index, 1);
	const up = (index: number) => (index > 0 ? () => move(group.items, index, -1) : undefined);
	const down = (index: number) =>
		index < group.items.length - 1 ? () => move(group.items, index, 1) : undefined;
</script>

<div
	class={cn(
		'flex flex-col gap-3 rounded-2xl border p-3',
		root ? 'bg-card' : 'border-dashed bg-secondary/40',
		top && 'border-0 p-0',
		error && 'border-destructive'
	)}
	data-key={group.key}
	role="group"
	aria-label={root ? m.rule_conditions() : m.rule_subgroup()}
>
	<div class="flex flex-wrap items-center gap-2">
		<Select
			aria-label={m.rule_mode()}
			value={group.mode}
			options={modes}
			onchange={(mode) => (group.mode = mode === 'any' ? 'any' : 'all')}
			class="h-10 w-full sm:w-56"
		/>
		<Choice bind:checked={group.negate}>{m.rule_negate()}</Choice>
		{#if !root}
			<div class="ml-auto flex gap-0.5">
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
		{/if}
	</div>

	{#each group.items as item, index (item.key)}
		{#if item.kind === 'group'}
			<ConditionGroup
				group={item}
				{model}
				{lookup}
				{errors}
				{steps}
				onremove={() => remove(index)}
				onup={up(index)}
				ondown={down(index)}
				{onunreadable}
			/>
		{:else}
			<ConditionRow
				condition={item}
				{lookup}
				{steps}
				error={errors[item.key]}
				onremove={() => remove(index)}
				onup={up(index)}
				ondown={down(index)}
				onunreadable={(unreadable) => onunreadable?.(item.key, unreadable)}
			/>
		{/if}
	{/each}

	{#if error}<Field.Error>{error}</Field.Error>{/if}

	<div class="flex flex-wrap gap-2">
		<Button
			variant="outline"
			size="sm"
			disabled={!canAddCondition(model)}
			onclick={() => group.items.push(newCondition(steps === null ? 'contact' : 'step'))}
		>
			<Plus aria-hidden="true" />
			{m.rule_add_condition()}
		</Button>
		<Button
			variant="outline"
			size="sm"
			disabled={!canAddGroup(model, group)}
			onclick={() =>
				group.items.push(
					newGroup(group.mode === 'all' ? 'any' : 'all', [
						newCondition(steps === null ? 'contact' : 'step')
					])
				)}
		>
			<ListPlus aria-hidden="true" />
			{m.rule_add_group()}
		</Button>
	</div>
</div>
