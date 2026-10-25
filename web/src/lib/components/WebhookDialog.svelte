<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { DOCUMENT_EVENT_TYPES, type DocumentEventType } from '#lib/events.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';

	type Webhook = components['schemas']['WebhookOut'];
	type Created = components['schemas']['WebhookCreated'];

	// Create or change a webhook. A new one answers with its secret, handed on to `oncreated`.
	let {
		open = $bindable(false),
		webhook = null,
		onsaved,
		oncreated
	}: {
		open?: boolean;
		webhook?: Webhook | null;
		onsaved: () => void;
		oncreated: (created: Created) => void;
	} = $props();

	let name = $state('');
	let url = $state('');
	let all = $state(true);
	let types = $state<string[]>([]);
	let active = $state(true);

	const labels: Record<DocumentEventType, () => string> = {
		'document.received': m.event_received,
		'document.node_started': m.event_node_started,
		'document.node_deferred': m.event_node_deferred,
		'document.node_completed': m.event_node_completed,
		'document.lane_changed': m.event_lane_changed,
		'document.filed': m.event_filed,
		'document.updated': m.event_updated,
		'document.deleted': m.event_deleted
	};

	$effect(() => {
		if (!open) return;
		name = webhook?.name ?? '';
		url = webhook?.url ?? '';
		all = webhook ? webhook.event_types.includes('*') : true;
		types = webhook ? webhook.event_types.filter((type) => type !== '*') : [];
		active = webhook?.active ?? true;
	});

	async function save() {
		const event_types = all ? ['*'] : types;
		if (webhook) {
			await unwrap(
				api.PATCH('/api/v1/webhooks/{id}', {
					params: { path: { id: webhook.id } },
					body: { name: name.trim(), url: url.trim(), event_types, active }
				})
			);
			toast.success(m.webhook_saved());
			onsaved();
		} else {
			const created = await unwrap(
				api.POST('/api/v1/webhooks', {
					body: { name: name.trim(), url: url.trim(), event_types, active }
				})
			);
			onsaved();
			oncreated(created);
		}
	}
</script>

<FormDialog
	bind:open
	title={webhook ? m.webhook_edit() : m.webhook_new()}
	submitLabel={webhook ? m.save() : m.create()}
	disabled={name.trim() === '' || url.trim() === '' || (!all && types.length === 0)}
	class="max-w-lg"
	action={save}
>
	<Field.Field>
		<Field.Label for="wh-name">{m.field_name()}</Field.Label>
		<Input id="wh-name" bind:value={name} maxlength={100} required />
	</Field.Field>
	<Field.Field>
		<Field.Label for="wh-url">{m.webhook_url()}</Field.Label>
		<Input id="wh-url" type="url" bind:value={url} maxlength={2000} required />
		<Field.Description>{m.webhook_url_hint()}</Field.Description>
	</Field.Field>
	<fieldset class="flex flex-col gap-2">
		<legend class="mb-1 text-sm font-medium">{m.webhook_events()}</legend>
		<label class="flex items-center gap-2 text-sm">
			<input type="checkbox" bind:checked={all} class="size-4 accent-primary" />
			{m.webhook_events_all()}
		</label>
		{#if !all}
			{#each DOCUMENT_EVENT_TYPES as type (type)}
				<label class="flex items-center gap-2 pl-6 text-sm">
					<input type="checkbox" value={type} bind:group={types} class="size-4 accent-primary" />
					{labels[type]()}
				</label>
			{/each}
		{/if}
	</fieldset>
	<label class="flex items-center gap-2 text-sm">
		<input type="checkbox" bind:checked={active} class="size-4 accent-primary" />
		{m.webhook_active()}
	</label>
</FormDialog>
