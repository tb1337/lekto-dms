<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import X from '@lucide/svelte/icons/x';
	import NativeSelect from '#lib/components/NativeSelect.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import {
		IDENTIFIER_KINDS,
		type IdentifierRow,
		type IdentifierSource,
		kindLabel,
		row
	} from '#lib/identifiers.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A contact's identifiers: those entered by hand can be changed and removed; learned ones
	// can be taken over (then they are entered by hand) or rejected (training does not learn
	// them again); a rejected one can be allowed again.
	let { rows = $bindable() }: { rows: IdentifierRow[] } = $props();

	const kinds = IDENTIFIER_KINDS.map((kind) => ({ value: kind, label: kindLabel(kind) }));

	function become(item: IdentifierRow, source: IdentifierSource) {
		rows = rows.map((other) => (other.key === item.key ? { ...other, source } : other));
	}

	function drop(item: IdentifierRow) {
		rows = rows.filter((other) => other.key !== item.key);
	}
</script>

<div class="flex flex-col gap-2">
	{#each rows as item, index (item.key)}
		{#if item.source === 'manual'}
			<div class="flex items-center gap-2">
				<NativeSelect
					bind:value={rows[index].kind}
					options={kinds}
					aria-label={m.identifier_kind()}
					class="w-44 shrink-0"
				/>
				<Input
					bind:value={rows[index].value}
					aria-label={m.identifier_value()}
					maxlength={100}
					class="min-w-0 flex-1"
				/>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					aria-label={m.identifier_remove()}
					onclick={() => drop(item)}
				>
					<X aria-hidden="true" />
				</Button>
			</div>
		{:else}
			<div class="flex flex-wrap items-center gap-2 rounded-xl border border-dashed px-3 py-1.5">
				<span
					class={[
						'min-w-0 flex-1 truncate text-sm',
						item.source === 'rejected' && 'text-muted-foreground line-through'
					]}
				>
					{kindLabel(item.kind)}:&nbsp;<span class="font-mono">{item.value}</span>
				</span>
				<Badge variant={item.source === 'learned' ? 'secondary' : 'outline'}>
					{item.source === 'learned' ? m.identifier_learned() : m.identifier_rejected()}
				</Badge>
				{#if item.source === 'learned'}
					<Button type="button" variant="ghost" size="sm" onclick={() => become(item, 'manual')}>
						{m.identifier_keep()}
					</Button>
					<Button type="button" variant="ghost" size="sm" onclick={() => become(item, 'rejected')}>
						{m.identifier_reject()}
					</Button>
				{:else}
					<Button type="button" variant="ghost" size="sm" onclick={() => drop(item)}>
						{m.identifier_unblock()}
					</Button>
				{/if}
			</div>
		{/if}
	{/each}
	<div>
		<Button type="button" variant="outline" size="sm" onclick={() => (rows = [...rows, row()])}>
			<Plus aria-hidden="true" />
			{m.identifier_add()}
		</Button>
	</div>
</div>
