<script lang="ts" module>
	export interface SearchOption {
		value: string;
		label: string;
		/** A second line, searched too: a tag's path. */
		hint?: string;
		/** Searched, not shown: a contact's aliases. */
		keywords?: string;
	}
</script>

<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';
	import type { Snippet } from 'svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import PhoneSheet from '#lib/components/PhoneSheet.svelte';
	import * as Command from '#lib/components/ui/command/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { matchesWords, searchWords } from '#lib/picking.ts';
	import { cn } from '#lib/utils.ts';
	import { FIELD, FIELD_HEIGHT } from '#lib/components/ui/field-look.ts';

	// A choice from a long list, by searching: contact, document type, topic. Closed it looks like
	// a `Select` (the chosen one as `chosen` draws it, else its label, else `placeholder`; a value
	// the options do not hold, deleted or out of sight, says so rather than that none is set); open,
	// a search over label and hint, "none" first while nothing is typed. With `create` (admins)
	// a search that names nothing offers "„…“ anlegen …": the choice gives way to `create`'s
	// dialog, and the one it makes is chosen. A popover on wider screens; on a phone a sheet from
	// the bottom (`PhoneSheet`) named `title`, with rows a finger hits (Tobi, 28.10.2026).
	let {
		value = $bindable(''),
		options,
		title,
		id,
		disabled = false,
		placeholder,
		noneLabel,
		searchLabel = m.assignment_search(),
		onchange,
		create,
		chosen
	}: {
		value?: string;
		options: readonly SearchOption[];
		/** The sheet's heading on a phone: "Kontakt wählen". */
		title: string;
		id?: string;
		disabled?: boolean;
		/** What the field says without a value. */
		placeholder: string;
		/** The entry that clears the value. */
		noneLabel: string;
		searchLabel?: string;
		/** Called with the new value when the user picks one. */
		onchange?: (value: string) => void;
		/** Make an entry named so to begin with (a dialog); null when it closed without. */
		create?: (name: string) => Promise<SearchOption | null>;
		chosen?: Snippet<[SearchOption]>;
	} = $props();

	const NONE = 'none:';
	let open = $state(false);
	let query = $state('');
	// Entries made here, until `options` hold them too.
	let made = $state<SearchOption[]>([]);
	const all = $derived([
		...options,
		...made.filter((entry) => !options.some((option) => option.value === entry.value))
	]);
	const current = $derived(all.find((option) => option.value === value) ?? null);
	const words = $derived(searchWords(query));
	const found = $derived(
		all.filter((option) =>
			matchesWords(`${option.label} ${option.hint ?? ''} ${option.keywords ?? ''}`, words)
		)
	);
	const offered = $derived(
		create !== undefined &&
			words !== '' &&
			!all.some((option) => option.label.trim().toLocaleLowerCase() === words)
	);

	function pick(next: string) {
		value = next;
		open = false;
		query = '';
		onchange?.(next);
	}

	/** Make what the search names: the choice closes, a dialog comes over the page. */
	async function make(how: (name: string) => Promise<SearchOption | null>) {
		const name = query.trim();
		open = false;
		query = '';
		const entry = await how(name);
		if (!entry) return;
		made = [...made, entry];
		pick(entry.value);
	}
</script>

{#snippet field(props: Record<string, unknown>)}
	<!-- A combobox as a `Select` is one: named by its label, its value read out. -->
	<button
		{...props}
		type="button"
		{id}
		{disabled}
		role="combobox"
		data-value={value}
		class={cn(FIELD, FIELD_HEIGHT, 'flex items-center gap-2 text-left')}
	>
		{#if current && chosen}
			{@render chosen(current)}
		{:else if current}
			<span class="min-w-0 flex-1 truncate">{current.label}</span>
		{:else if value !== ''}
			<span class="min-w-0 flex-1 truncate">{m.rule_unknown()}</span>
		{:else}
			<span class="min-w-0 flex-1 truncate text-muted-foreground">{placeholder}</span>
		{/if}
		<ChevronDown class="ml-auto size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
	</button>
{/snippet}

{#snippet list(row: string)}
	<Command.Root shouldFilter={false} class="min-h-0 flex-1">
		<Command.Input bind:value={query} placeholder={searchLabel} aria-label={searchLabel} />
		<Command.List class={cn(phone.current && 'max-h-none flex-1 px-2 pt-2 pb-4')}>
			<Command.Empty class="py-4 text-center text-sm text-muted-foreground">
				{m.assignment_none_found()}
			</Command.Empty>
			{#if words === ''}
				<Command.Item value={NONE} onSelect={() => pick('')} class={row}>
					<span class="flex-1">{noneLabel}</span>
					{#if value === ''}<Check aria-hidden="true" />{/if}
				</Command.Item>
			{/if}
			{#each found as option (option.value)}
				<Command.Item value={option.value} onSelect={() => pick(option.value)} class={row}>
					<span class="flex min-w-0 flex-1 flex-col">
						<span class="truncate">{option.label}</span>
						{#if option.hint}
							<span class="truncate text-xs text-muted-foreground">{option.hint}</span>
						{/if}
					</span>
					{#if value === option.value}<Check aria-hidden="true" />{/if}
				</Command.Item>
			{/each}
			{#if offered && create}
				<Command.Group class={cn(found.length > 0 && 'border-t')}>
					<Command.Item value="create:" onSelect={() => make(create)} class={cn(row, 'text-brand')}>
						<Plus aria-hidden="true" class="text-brand" />
						{m.create_named({ name: query.trim() })}
					</Command.Item>
				</Command.Group>
			{/if}
		</Command.List>
	</Command.Root>
{/snippet}

{#if phone.current}
	{@render field({
		'aria-haspopup': 'dialog',
		'aria-expanded': open,
		onclick: () => (open = true)
	})}
	<PhoneSheet bind:open {title} onOpenChange={(next) => next || (query = '')}>
		{#snippet close()}
			<IconButton
				label={m.close()}
				onclick={() => {
					query = '';
					open = false;
				}}
			>
				<X aria-hidden="true" />
			</IconButton>
		{/snippet}
		{@render list('min-h-12 rounded-xl px-3')}
	</PhoneSheet>
{:else}
	<Popover.Root bind:open onOpenChange={(next) => next || (query = '')}>
		<Popover.Trigger>
			{#snippet child({ props })}
				{@render field(props)}
			{/snippet}
		</Popover.Trigger>
		<Popover.Content
			class="w-(--bits-popover-anchor-width) min-w-64 p-0"
			align="start"
			collisionPadding={8}
		>
			{@render list('')}
		</Popover.Content>
	</Popover.Root>
{/if}
