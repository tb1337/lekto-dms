<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { BASE } from '#lib/base.ts';
	import FieldDialog from '#lib/components/FieldDialog.svelte';
	import MasterDataDialog from '#lib/components/MasterDataDialog.svelte';
	import { describeError } from '#lib/errors.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import type { FieldDefinition, MasterData } from '#lib/masterdata.svelte.ts';
	import { type Item, KINDS, type SimpleKind, type Values } from '#lib/masterdata-api.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The dialogs that add and change master data, for every page (`masterDataDialogs.open`):
	// contacts, document types, tags and fields. A document type's dialog links the rule of its
	// title pattern, unless it was opened from that rule.
	const request = $derived(masterDataDialogs.request);
	const simple = $derived(
		request && request.kind !== 'fields' ? (request.kind as SimpleKind) : null
	);

	let item = $state<Item | null>(null);
	let field = $state<FieldDefinition | null>(null);
	let types = $state<MasterData[]>([]);
	let ruleId = $state<string | null>(null);
	let ready = $state(false);

	$effect(() => {
		const wanted = request;
		ready = false;
		item = null;
		field = null;
		ruleId = null;
		if (!wanted) return;
		let current = true;
		void (async () => {
			try {
				if (wanted.kind === 'fields') {
					types = await unwrap(api.GET('/api/v1/document-types'));
					field =
						typeof wanted.item === 'string'
							? await unwrap(
									api.GET('/api/v1/fields/{id}', { params: { path: { id: wanted.item } } })
								)
							: (wanted.item as FieldDefinition | null);
				} else {
					item =
						typeof wanted.item === 'string'
							? await KINDS[wanted.kind].get(wanted.item)
							: (wanted.item as Item | null);
					if (wanted.kind === 'document-types' && item && !wanted.fromRule) {
						const rules = await unwrap(
							api.GET('/api/v1/rules', { params: { query: { scope: 'global' } } })
						);
						const own = item.id;
						ruleId = rules.find((rule) => rule.managed_by_document_type_id === own)?.id ?? null;
					}
				}
				if (current) ready = true;
			} catch (failure) {
				if (!current) return;
				toast.error(describeError(failure));
				masterDataDialogs.close();
			}
		})();
		return () => {
			current = false;
		};
	});

	async function submit(values: Values) {
		if (!simple) return;
		const ops = KINDS[simple];
		if (item) {
			await ops.change(item.id, values);
			toast.success(m.master_saved());
		} else {
			await ops.create(values);
			toast.success(m.master_created());
		}
		masterDataDialogs.saved();
	}
</script>

{#if simple}
	<MasterDataDialog
		bind:open={() => ready && request !== null, (value) => !value && masterDataDialogs.close()}
		title={item ? m.master_edit({ name: item.name }) : KINDS[simple].add()}
		extra={KINDS[simple].extra}
		initial={item}
		submitLabel={item ? m.save() : m.create()}
		ruleHref={ruleId ? `${BASE}/rules/${ruleId}` : null}
		onsubmit={submit}
	/>
{:else if request?.kind === 'fields'}
	<FieldDialog
		bind:open={() => ready && request !== null, (value) => !value && masterDataDialogs.close()}
		initial={field}
		{types}
		onsaved={() => masterDataDialogs.saved()}
	/>
{/if}
