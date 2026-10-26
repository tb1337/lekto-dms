<script lang="ts">
	import Folder from '@lucide/svelte/icons/folder';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Users from '@lucide/svelte/icons/users';
	import type { components } from '#lib/api/schema.ts';
	import FieldGroup from '#lib/components/document/FieldGroup.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { memberChips, spaceName, whereText, type Filing, type Viewer } from '#lib/filing.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { userName, type Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { unseenText } from '#lib/space-suggestion.ts';
	import { cn } from '#lib/utils.ts';
	import { Choice, ChoiceBox } from '#lib/components/ui/choice/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';

	type Document = components['schemas']['DocumentDetails'];

	// Where the document lies and who sees it (Tobi, 22.10.2026). While the judge's space check
	// waits for a person (`filing`), a yellow box with the choices the signals offer, at the top
	// of the form; otherwise a calm one below the fields, with "Move".
	let {
		document,
		lookup,
		viewer,
		filing = null,
		choice = $bindable(''),
		other = $bindable(''),
		otherOptions = [],
		unseen = [],
		editable,
		canMove = false,
		onmove
	}: {
		document: Document;
		lookup: Lookup;
		viewer: Viewer;
		/** The open space check, worked out; null when there is nothing to decide. */
		filing?: Filing | null;
		/** The space chosen, `other` for "Another space", empty for none yet. */
		choice?: string;
		/** The space chosen under "Another space". */
		other?: string;
		otherOptions?: readonly { value: string; label: string }[];
		/** Users the document names who do not see it where the choice leads, by id. */
		unseen?: readonly string[];
		editable: boolean;
		/** There is a space to move the document into (the head knows; without one its own
		 * button is disabled too). */
		canMove?: boolean;
		/** "Move": the move dialog of the document's head. */
		onmove?: () => void;
	} = $props();

	const green = $derived(document.lane === 'green');
	const space = $derived(lookup.spaces.find((entry) => entry.id === document.space_id) ?? null);
	const uploader = $derived.by(() => {
		if (!document.uploaded_by) return m.filing_uploader_gone();
		const name = userName(lookup.users, document.uploaded_by);
		return document.uploaded_by === viewer.id ? m.filing_uploader_you({ name }) : name;
	});
	const warning = $derived(unseen.length > 0 ? unseenText(unseen, lookup) : '');
	const choices = $derived([{ value: '', label: m.filing_other_choose() }, ...otherOptions]);

	function pickOther(value: string) {
		other = value;
		if (value !== '') choice = 'other';
	}
</script>

{#snippet note()}
	{#if warning}
		<p
			class="flex items-start gap-2.5 rounded-xl bg-note px-3.5 py-3 text-sm text-note-foreground"
			data-testid="filing-unseen"
		>
			<Users class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
			<span>{warning}</span>
		</p>
	{/if}
{/snippet}

{#if filing}
	<section
		aria-labelledby="filing-title"
		data-testid="filing-open"
		class="flex flex-col gap-3 rounded-2xl border border-lane-yellow-foreground/25 bg-lane-yellow/25 p-4"
	>
		<div class="flex items-center gap-2.5">
			<TriangleAlert
				class="size-[18px] shrink-0 text-lane-yellow-foreground"
				aria-hidden="true"
				strokeWidth={2.2}
			/>
			<SectionTitle size="card" level={3} id="filing-title">
				{m.filing_title()}
			</SectionTitle>
			<span
				class="ml-auto rounded-full bg-lane-yellow px-2.5 py-0.5 text-xs font-medium text-lane-yellow-foreground"
			>
				{filing.status}
			</span>
		</div>
		<p class="text-sm text-muted-foreground">
			{whereText(document.space_id, lookup, viewer, green)}
		</p>
		<p class="font-medium">{filing.lead}</p>
		{@render note()}
		<fieldset class="flex flex-col gap-2" disabled={!editable}>
			<legend class="mb-2 text-xs font-medium text-muted-foreground">{m.filing_question()}</legend>
			{#each filing.options as option (option.value)}
				<label
					class={cn(
						'flex items-start gap-3 rounded-xl border bg-card p-3.5 has-[input[type=radio]:checked]:border-primary has-[input[type=radio]:checked]:ring-1 has-[input[type=radio]:checked]:ring-primary',
						option.choosable ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'
					)}
				>
					<ChoiceBox
						type="radio"
						name="filing"
						value={option.value}
						bind:group={choice}
						disabled={!option.choosable}
						class="mt-1"
					/>
					<span class="flex min-w-0 flex-col gap-1.5">
						<span class="flex flex-wrap items-center gap-2">
							<span class="font-semibold">{option.title}</span>
							{#if option.suggested}
								<span class="rounded-full bg-panel px-2 text-micro leading-5 font-medium text-brand"
									>{m.filing_suggested()}</span
								>
							{/if}
						</span>
						{#if option.chips.length > 0}
							<span class="flex flex-wrap gap-1.5">
								{#each option.chips as chip, index (index)}
									<span
										class={cn(
											'rounded-full px-2.5 py-0.5 text-xs',
											chip.strong ? 'bg-panel text-brand' : 'bg-muted text-muted-foreground'
										)}>{chip.text}</span
									>
								{/each}
							</span>
						{/if}
						<span class="text-sm text-muted-foreground">
							{option.choosable ? option.consequence : m.filing_unavailable()}
						</span>
					</span>
				</label>
			{/each}
			{#if otherOptions.length > 0}
				<div
					class="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3.5 has-[input[type=radio]:checked]:border-primary has-[input[type=radio]:checked]:ring-1 has-[input[type=radio]:checked]:ring-primary"
				>
					<Choice type="radio" name="filing" value="other" bind:group={choice} class="text-base">
						<span class="font-semibold">{m.filing_other()}</span>
					</Choice>
					<div class="ml-auto min-w-[12rem] flex-1">
						<Select
							id="filing-other"
							value={other}
							options={choices}
							aria-label={m.filing_other()}
							onchange={pickOther}
						/>
					</div>
				</div>
			{/if}
		</fieldset>
	</section>
{:else}
	{#snippet move()}
		{#if editable && onmove}
			<Button
				type="button"
				variant="outline"
				size="sm"
				class="ml-auto"
				disabled={!canMove}
				onclick={onmove}
			>
				{m.filing_move_action()}
			</Button>
		{/if}
	{/snippet}
	<FieldGroup
		id="filing-title"
		icon={Folder}
		title={m.filing_title()}
		hint={m.filing_hint()}
		action={move}
		class="gap-3 pb-4"
		data-testid="filing-calm"
	>
		<dl class="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-sm">
			<dt class="text-muted-foreground">{m.filing_space()}</dt>
			<dd class="font-semibold">{spaceName(document.space_id, lookup, viewer)}</dd>
			{#if space}
				<dt class="text-muted-foreground">{m.filing_visible()}</dt>
				<dd class="flex flex-wrap gap-1.5">
					{#each memberChips(space.members, viewer, green) as chip (chip.key)}
						<span class="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
							>{chip.text}</span
						>
					{/each}
				</dd>
			{/if}
			<dt class="text-muted-foreground">{m.filing_uploaded()}</dt>
			<dd>{uploader}</dd>
			<dt class="text-muted-foreground">{m.filing_decided()}</dt>
			<dd class="text-muted-foreground">
				{document.space_confirmed_at
					? m.filing_decided_at({ date: formatDate(document.space_confirmed_at) })
					: m.filing_decided_lekto()}
			</dd>
		</dl>
		{@render note()}
	</FieldGroup>
{/if}
