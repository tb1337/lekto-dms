<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import TemplateInput from '#lib/components/templates/TemplateInput.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { WEBHOOK_EVENT_TYPES, type WebhookEventType } from '#lib/events.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { Choice } from '#lib/components/ui/choice/index.ts';

	type Webhook = components['schemas']['WebhookOut'];
	type Created = components['schemas']['WebhookCreated'];
	type Body = components['schemas']['BodyFormat'];
	type ModelCall = components['schemas']['ModelCallKind'];
	// A header of the webhook's own. `kept`: it is stored already, its value hidden; left empty,
	// the value stays as it is.
	type Header = { name: string; value: string; kept: boolean };

	// Create or change a webhook. A new secret (creating a signed webhook, or switching signing
	// on) is handed on to `oncreated`, which shows it once.
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
	let signed = $state(true);
	let headers = $state<Header[]>([]);
	let body = $state<Body>('thin');
	let template = $state('');
	let openTasks = $state(4);
	// The model call the webhook answers instead of the language model ('' for none) and its
	// time to answer, in minutes. Only admins give it, to an admin's webhook (the API checks the
	// owner); one they see on another's webhook they may take away.
	let modelCall = $state<ModelCall | ''>('');
	let callMinutes = $state(5);

	const modelCalls = $derived([
		{ value: '', label: m.webhook_model_call_none() },
		{ value: 'propose', label: m.webhook_model_call_propose() },
		{ value: 'extract', label: m.webhook_model_call_extract() }
	]);
	const showsModelCall = $derived(
		session.isAdmin &&
			(!webhook || webhook.owner_id === session.user?.id || webhook.model_call !== null)
	);
	const callMinutesValid = $derived(
		modelCall === '' || (Number.isFinite(callMinutes) && callMinutes >= 0.5 && callMinutes <= 1440)
	);

	const bodies = $derived([
		{ value: 'thin', label: m.webhook_body_thin(), hint: m.webhook_body_thin_hint() },
		{ value: 'full', label: m.webhook_body_full(), hint: m.webhook_body_full_hint() },
		{ value: 'template', label: m.webhook_body_template(), hint: m.webhook_body_template_hint() }
	]);
	const bodyHint = $derived(bodies.find((option) => option.value === body)?.hint ?? '');

	const labels: Record<WebhookEventType, () => string> = {
		'document.received': m.event_received,
		'document.node_started': m.event_node_started,
		'document.node_deferred': m.event_node_deferred,
		'document.node_delegated': m.event_node_delegated,
		'document.node_completed': m.event_node_completed,
		'document.lane_changed': m.event_lane_changed,
		'document.filed': m.event_filed,
		'document.updated': m.event_updated,
		'document.deleted': m.event_deleted,
		'document.review_required': m.event_review_required,
		'document.confirmed': m.event_confirmed,
		'document.moved': m.event_moved
	};

	$effect(() => {
		if (!open) return;
		name = webhook?.name ?? '';
		url = webhook?.url ?? '';
		all = webhook ? webhook.event_types.includes('*') : true;
		types = webhook ? webhook.event_types.filter((type) => type !== '*') : [];
		active = webhook?.active ?? true;
		signed = webhook?.signed ?? true;
		headers = (webhook?.headers ?? []).map((header) => ({ name: header, value: '', kept: true }));
		body = webhook?.body ?? 'thin';
		template = webhook?.body_template ?? '';
		openTasks = webhook?.max_open_tasks ?? 4;
		modelCall = webhook?.model_call?.kind ?? '';
		callMinutes = (webhook?.model_call?.timeout_seconds ?? 300) / 60;
	});

	function modelCallBody() {
		return modelCall === ''
			? null
			: { kind: modelCall, timeout_seconds: Math.round(callMinutes * 60) };
	}

	// A new header needs a value; a kept one may stay empty (unchanged).
	const headersComplete = $derived(
		headers.every((header) => header.name.trim() !== '' && (header.kept || header.value !== ''))
	);
	// Only changed headers go to the API: a value that cannot be read any more is not asked for
	// when the headers were not touched.
	const headersChanged = $derived(
		headers.some((header) => header.value !== '' || !header.kept) ||
			headers.map((header) => header.name.trim()).join('\n') !== (webhook?.headers ?? []).join('\n')
	);

	function headerBody() {
		return headers.map((header) =>
			header.value === ''
				? { name: header.name.trim() }
				: { name: header.name.trim(), value: header.value }
		);
	}

	async function save() {
		const event_types = all ? ['*'] : types;
		const content = {
			body,
			body_template: body === 'template' ? template : null,
			max_open_tasks: openTasks,
			...(showsModelCall ? { model_call: modelCallBody() } : {})
		};
		if (webhook) {
			await unwrap(
				api.PATCH('/api/v1/webhooks/{id}', {
					params: { path: { id: webhook.id } },
					body: {
						name: name.trim(),
						url: url.trim(),
						event_types,
						active,
						...content,
						...(headersChanged ? { headers: headerBody() } : {})
					}
				})
			);
			const path = { params: { path: { id: webhook.id } } };
			if (signed && !webhook.signed)
				oncreated(await unwrap(api.POST('/api/v1/webhooks/{id}/secret', path)));
			if (!signed && webhook.signed) await unwrap(api.DELETE('/api/v1/webhooks/{id}/secret', path));
			toast.success(m.webhook_saved());
			onsaved();
		} else {
			const created = await unwrap(
				api.POST('/api/v1/webhooks', {
					body: {
						name: name.trim(),
						url: url.trim(),
						event_types,
						active,
						signed,
						...content,
						headers: headers.map((header) => ({ name: header.name.trim(), value: header.value }))
					}
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
	disabled={name.trim() === '' ||
		url.trim() === '' ||
		!headersComplete ||
		(body === 'template' && template.trim() === '') ||
		!(Number.isInteger(openTasks) && openTasks >= 1 && openTasks <= 64) ||
		!callMinutesValid}
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
		<Choice bind:checked={all}>{m.webhook_events_all()}</Choice>
		{#if !all}
			<p class="pl-6 text-sm text-muted-foreground">{m.webhook_events_none_hint()}</p>
			{#each WEBHOOK_EVENT_TYPES as type (type)}
				<Choice value={type} bind:group={types} class="ml-6">{labels[type]()}</Choice>
			{/each}
		{/if}
	</fieldset>
	<div class="flex flex-col gap-2">
		<span id="wh-body" class="text-sm font-medium">{m.webhook_body()}</span>
		<Segmented
			bind:value={() => body, (next) => (body = next as Body)}
			options={bodies}
			labelledby="wh-body"
		/>
		<p class="text-sm text-muted-foreground">{bodyHint}</p>
		{#if body === 'template'}
			<TemplateInput
				id="wh-template"
				bind:value={template}
				label={m.webhook_body_template()}
				purpose="webhook"
				maxlength={10000}
			/>
		{/if}
	</div>
	<fieldset class="flex flex-col gap-2">
		<legend class="mb-1 text-sm font-medium">{m.webhook_headers()}</legend>
		{#each headers as header, index (index)}
			<div class="flex items-center gap-2">
				<Input
					aria-label={m.webhook_header_name()}
					class="font-mono"
					bind:value={header.name}
					maxlength={100}
					required
				/>
				<Input
					aria-label={m.webhook_header_value()}
					type="password"
					autocomplete="new-password"
					class="font-mono"
					placeholder={header.kept ? m.webhook_header_kept() : ''}
					bind:value={header.value}
					maxlength={4096}
				/>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					aria-label={m.webhook_header_remove({ name: header.name })}
					onclick={() => headers.splice(index, 1)}
				>
					<Trash2 aria-hidden="true" />
				</Button>
			</div>
		{/each}
		<div>
			<Button
				type="button"
				variant="outline"
				disabled={headers.length >= 20}
				onclick={() => headers.push({ name: '', value: '', kept: false })}
			>
				<Plus aria-hidden="true" />
				{m.webhook_header_add()}
			</Button>
		</div>
		<p class="text-sm text-muted-foreground">{m.webhook_headers_hint()}</p>
	</fieldset>
	<Field.Field>
		<Field.Label for="wh-open-tasks">{m.webhook_open_tasks()}</Field.Label>
		<Input
			id="wh-open-tasks"
			type="number"
			min={1}
			max={64}
			step={1}
			class="w-24"
			bind:value={openTasks}
			required
		/>
		<Field.Description>{m.webhook_open_tasks_hint()}</Field.Description>
	</Field.Field>
	{#if showsModelCall}
		<div class="flex flex-col gap-2">
			<div class="flex flex-wrap items-end gap-3">
				<Field.Field class="min-w-48 flex-1">
					<Field.Label for="wh-model-call">{m.webhook_model_call()}</Field.Label>
					<Select
						id="wh-model-call"
						value={modelCall}
						options={modelCalls}
						onchange={(next) => (modelCall = next as ModelCall | '')}
						class="h-10"
					/>
				</Field.Field>
				{#if modelCall !== ''}
					<Field.Field class="w-40">
						<Field.Label for="wh-model-call-time">{m.webhook_model_call_time()}</Field.Label>
						<Input
							id="wh-model-call-time"
							type="number"
							min={0.5}
							max={1440}
							step={0.5}
							aria-invalid={!callMinutesValid || undefined}
							bind:value={callMinutes}
						/>
					</Field.Field>
				{/if}
			</div>
			<p class="text-sm text-muted-foreground">{m.webhook_model_call_hint()}</p>
		</div>
	{/if}
	<Field.Field>
		<Choice bind:checked={signed}>{m.webhook_signed()}</Choice>
		<Field.Description>{m.webhook_signed_hint()}</Field.Description>
	</Field.Field>
	<Choice bind:checked={active}>{m.webhook_active()}</Choice>
</FormDialog>
