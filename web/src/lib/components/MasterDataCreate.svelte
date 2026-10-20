<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import MasterDataDialog from '#lib/components/MasterDataDialog.svelte';
	import { describeError } from '#lib/errors.ts';
	import { logoFetching } from '#lib/logos.ts';
	import { type CreateRequest, masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import type { FieldDefinition, Tag } from '#lib/masterdata.svelte.ts';
	import { isTagKind, KINDS, TAG_KINDS, type Values } from '#lib/masterdata-api.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A dialog that makes a contact, document type or tag for a picker (`masterDataDialogs.create`)
	// over the page or the dialog it is in: the name searched for filled in. It loads what its
	// kind needs first (every tag; for a type the fields; for a contact whether logos can be
	// fetched). Saving makes it and hands it to the picker; closing without hands back null.
	let { request }: { request: CreateRequest } = $props();

	let data = $state<{ tags: Tag[]; fields: FieldDefinition[] | null; fetching: boolean } | null>(
		null
	);

	$effect(() => {
		const kind = request.kind;
		let current = true;
		Promise.all([
			unwrap(api.GET('/api/v1/tags')),
			kind === 'document-types' ? unwrap(api.GET('/api/v1/fields')) : Promise.resolve(null),
			kind === 'contacts' ? logoFetching() : Promise.resolve(false)
		]).then(
			([tags, fields, fetching]) => {
				if (current) data = { tags, fields, fetching };
			},
			(failure) => {
				if (!current) return;
				toast.error(describeError(failure));
				masterDataDialogs.finish(null, request);
			}
		);
		return () => {
			current = false;
		};
	});

	// A group or topic made in this dialog: there at once.
	function tagCreated(tag: Tag) {
		if (data) data = { ...data, tags: [...data.tags.filter((other) => other.id !== tag.id), tag] };
	}

	async function submit(values: Values) {
		const made = await KINDS[request.kind].create(values);
		// A document type's fields, after the type: it needs its id first.
		if (values.fields) {
			await unwrap(
				api.PUT('/api/v1/document-types/{id}/fields', {
					params: { path: { id: made.id } },
					body: { fields: values.fields.map(({ id, required }) => ({ field_id: id, required })) }
				})
			);
		}
		toast.success(m.master_created());
		masterDataDialogs.saved();
		masterDataDialogs.finish(made, request);
	}
</script>

<MasterDataDialog
	bind:open={() => data !== null, (value) => !value && masterDataDialogs.finish(null, request)}
	title={KINDS[request.kind].add()}
	extra={KINDS[request.kind].extra}
	presetName={request.name}
	submitLabel={m.create()}
	tags={data?.tags ?? []}
	fields={data?.fields ?? null}
	scope={isTagKind(request.kind) ? TAG_KINDS[request.kind] : null}
	fetching={data?.fetching ?? false}
	ontagcreated={tagCreated}
	onsubmit={submit}
/>
