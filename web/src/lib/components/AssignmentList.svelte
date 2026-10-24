<script lang="ts" module>
	export interface Assignment {
		id: string;
		required: boolean;
	}

	export interface Candidate {
		id: string;
		name: string;
		/** A second line in the search (a field's key, say). */
		hint?: string | null;
	}
</script>

<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as Command from '#lib/components/ui/command/index.ts';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { matchesWords, searchWords } from '#lib/picking.ts';
	import { cn } from '#lib/utils.ts';

	// What belongs to an item of master data, out of many: the assigned ones as rows (name,
	// required, remove), more added through a search, so that the list stays short however
	// many there are. A field's document types, a document type's fields.
	let {
		assigned,
		candidates,
		label,
		addLabel,
		emptyLabel,
		onchange
	}: {
		assigned: readonly Assignment[];
		candidates: readonly Candidate[];
		label: string;
		addLabel: string;
		emptyLabel: string;
		onchange: (assigned: Assignment[]) => void;
	} = $props();

	let open = $state(false);
	let query = $state('');

	const byId = $derived(new Map(candidates.map((candidate) => [candidate.id, candidate])));
	const nameOf = (id: string) => byId.get(id)?.name ?? id;
	const rows = $derived([...assigned].sort((a, b) => nameOf(a.id).localeCompare(nameOf(b.id))));
	const free = $derived(
		candidates.filter((candidate) => !assigned.some((item) => item.id === candidate.id))
	);
	const words = $derived(searchWords(query));
	const shown = $derived(free.filter((candidate) => matchesWords(candidate.name, words)));

	function add(id: string) {
		onchange([...assigned, { id, required: false }]);
		open = false;
		query = '';
	}

	function require(id: string, required: boolean) {
		onchange(assigned.map((item) => (item.id === id ? { ...item, required } : item)));
	}
</script>

<div class="flex flex-col gap-2" role="group" aria-label={label}>
	{#if rows.length === 0}
		<p class="rounded-xl border border-dashed px-3 py-2.5 text-sm text-muted-foreground">
			{emptyLabel}
		</p>
	{:else}
		<ul class="flex flex-col divide-y rounded-xl border">
			{#each rows as item (item.id)}
				{@const name = nameOf(item.id)}
				<li class="flex items-center gap-3 px-3 py-1.5">
					<span class="min-w-0 flex-1 truncate text-sm">{name}</span>
					<label class="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
						{m.assignment_required()}
						<Switch
							checked={item.required}
							onCheckedChange={(checked) => require(item.id, checked)}
							aria-label={m.assignment_required_for({ name })}
						/>
					</label>
					<Button
						type="button"
						variant="ghost"
						size="icon"
						class="size-8 shrink-0"
						aria-label={m.assignment_remove({ name })}
						onclick={() => onchange(assigned.filter((entry) => entry.id !== item.id))}
					>
						<X aria-hidden="true" />
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
	{#if free.length > 0}
		<Popover.Root bind:open>
			<Popover.Trigger
				class={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-fit')}
				aria-label={addLabel}
			>
				<Plus aria-hidden="true" />
				{addLabel}
			</Popover.Trigger>
			<Popover.Content class="w-72 p-0" align="start">
				<Command.Root shouldFilter={false}>
					<Command.Input
						bind:value={query}
						placeholder={m.assignment_search()}
						aria-label={m.assignment_search()}
					/>
					<Command.List>
						<Command.Empty class="py-4 text-center text-sm text-muted-foreground">
							{m.assignment_none_found()}
						</Command.Empty>
						{#each shown as candidate (candidate.id)}
							<Command.Item
								value={candidate.id}
								onSelect={() => add(candidate.id)}
								class="flex-col items-start gap-0"
							>
								<span class="max-w-full truncate">{candidate.name}</span>
								{#if candidate.hint}
									<span class="max-w-full truncate font-mono text-xs text-muted-foreground">
										{candidate.hint}
									</span>
								{/if}
							</Command.Item>
						{/each}
					</Command.List>
				</Command.Root>
			</Popover.Content>
		</Popover.Root>
	{/if}
</div>
