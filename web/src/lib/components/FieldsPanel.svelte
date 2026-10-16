<script lang="ts">
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { BASE } from '#lib/base.ts';
	import DocumentCount from '#lib/components/DocumentCount.svelte';
	import { unwrap } from '#lib/api/call.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { fieldTypeLabel } from '#lib/fields.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import type { FieldDefinition, MasterData } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { scope } from '#lib/scope.svelte.ts';

	let fields = $state<FieldDefinition[] | null>(null);
	let types = $state<MasterData[]>([]);
	let problem = $state<string | null>(null);
	let removing = $state<FieldDefinition | null>(null);

	async function load() {
		try {
			[fields, types] = await Promise.all([
				unwrap(
					api.GET('/api/v1/fields', {
						params: { query: { document_counts: true, all_users: scope.query } }
					})
				),
				unwrap(api.GET('/api/v1/document-types'))
			]);
			problem = null;
		} catch (failure) {
			problem = describeError(failure);
		}
	}
	// Again after a dialog saved (wherever it was opened), and with another scope.
	$effect(() => {
		void masterDataDialogs.changed;
		void scope.allUsers;
		void load();
	});

	function scopeText(field: FieldDefinition): string {
		if (field.document_type_ids === null) {
			const all = m.field_def_scope_global();
			return field.required ? m.field_def_required_in({ scope: all }) : all;
		}
		return field.document_type_ids
			.map((id) => {
				const label = types.find((type) => type.id === id)?.name ?? id;
				return field.required_document_type_ids.includes(id)
					? m.field_def_required_in({ scope: label })
					: label;
			})
			.join(', ');
	}

	async function remove() {
		if (!removing) return;
		await unwrap(api.DELETE('/api/v1/fields/{id}', { params: { path: { id: removing.id } } }));
		toast.success(m.master_deleted());
		await load();
	}
</script>

<div class="flex flex-col gap-4">
	<div>
		<Button onclick={() => masterDataDialogs.open('fields')}>
			<Plus aria-hidden="true" />
			{m.master_add_field()}
		</Button>
	</div>
	{#if problem}
		<p class="text-destructive" role="alert">{problem}</p>
	{:else if !fields}
		<p class="text-muted-foreground">{m.loading()}</p>
	{:else if fields.length === 0}
		<p
			class="rounded-2xl border border-dashed bg-card px-6 py-10 text-center text-muted-foreground"
		>
			{m.master_none()}
		</p>
	{:else}
		<ul class="flex flex-col gap-2">
			{#each fields as field (field.id)}
				<li class="flex items-center gap-3 rounded-2xl border bg-card px-4 py-2">
					<div class="flex min-w-0 flex-1 flex-col">
						<span class="flex min-w-0 flex-wrap items-baseline gap-x-2">
							<span class="truncate">{field.name}</span>
							<code
								class="truncate font-mono text-xs text-muted-foreground"
								title={m.field_def_key_hint()}>{`field.${field.key}`}</code
							>
						</span>
						<span class="truncate text-sm text-muted-foreground">
							{fieldTypeLabel(field.data_type)} · {scopeText(field)}
							{#if field.assignment === 'manual'}
								· {m.field_def_manual()}{/if}
							{#if field.choices.length > 0}
								· {field.choices.join(', ')}{/if}
						</span>
						{#if field.description}
							<span class="line-clamp-2 text-sm text-muted-foreground italic">
								{field.description}
							</span>
						{/if}
					</div>
					<DocumentCount count={field.document_count} href="{BASE}/documents?field={field.id}" />
					<Button
						variant="ghost"
						size="icon"
						aria-label={m.master_rename({ name: field.name })}
						onclick={() => masterDataDialogs.open('fields', field)}
					>
						<Pencil aria-hidden="true" />
					</Button>
					<Button
						variant="ghost"
						size="icon"
						aria-label={m.master_delete({ name: field.name })}
						onclick={() => (removing = field)}
					>
						<Trash2 aria-hidden="true" />
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<ConfirmDialog
	bind:open={() => removing !== null, (open) => !open && (removing = null)}
	title={m.master_delete({ name: removing?.name ?? '' })}
	description={m.master_delete_confirm()}
	confirmLabel={m.delete_title()}
	onconfirm={remove}
/>
