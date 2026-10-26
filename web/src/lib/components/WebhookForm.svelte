<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import type { components } from '#lib/api/schema.ts';
	import AsyncForm from '#lib/components/AsyncForm.svelte';
	import HintLabel from '#lib/components/HintLabel.svelte';
	import InfoHint from '#lib/components/InfoHint.svelte';
	import SecretDialog from '#lib/components/SecretDialog.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import TemplateInput from '#lib/components/templates/TemplateInput.svelte';
	import { Button, buttonVariants } from '#lib/components/ui/button/index.ts';
	import { Choice } from '#lib/components/ui/choice/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { WEBHOOK_EVENT_TYPES, type WebhookEventType } from '#lib/events.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import IconButton from '#lib/components/IconButton.svelte';

	type Webhook = components['schemas']['WebhookOut'];
	type Body = components['schemas']['BodyFormat'];
	type ModelCall = components['schemas']['ModelCallKind'];
	// A header of the webhook's own. `kept`: it is stored already, its value hidden; left empty,
	// the value stays as it is.
	type Header = { name: string; value: string; kept: boolean };

	// The form of a webhook on its own page (Tobi, 26.10.2026; a dialog before): create one
	// (`webhook` null) or change it. A new secret (creating a signed webhook, or switching
	// signing on) is shown once, here; `ondone` gets the webhook's id once it is saved and the
	// secret, if any, was seen.
	let {
		webhook = null,
		cancelHref,
		ondone
	}: {
		webhook?: Webhook | null;
		cancelHref: string;
		ondone: (id: string) => void;
	} = $props();

	// The form starts from the webhook as given; the page makes it anew for another one.
	const given = untrack(() => webhook);
	let name = $state(given?.name ?? '');
	let url = $state(given?.url ?? '');
	let all = $state(given ? given.event_types.includes('*') : true);
	let types = $state<string[]>(given ? given.event_types.filter((type) => type !== '*') : []);
	let active = $state(given?.active ?? true);
	let signed = $state(given?.signed ?? true);
	let headers = $state<Header[]>(
		(given?.headers ?? []).map((header) => ({ name: header, value: '', kept: true }))
	);
	let body = $state<Body>(given?.body ?? 'thin');
	let template = $state(given?.body_template ?? '');
	let openTasks = $state(given?.max_open_tasks ?? 4);
	// The model call the webhook answers instead of the language model ('' for none) and its
	// time to answer, in minutes. Only admins give it, to an admin's webhook (the API checks the
	// owner); one they see on another's webhook they may take away.
	let modelCall = $state<ModelCall | ''>(given?.model_call?.kind ?? '');
	let callMinutes = $state((given?.model_call?.timeout_seconds ?? 300) / 60);
	// The secret to show once, and where to go after it.
	let secret = $state<{ webhook: string; value: string } | null>(null);
	let savedId = $state<string | null>(null);

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
	const incomplete = $derived(
		name.trim() === '' ||
			url.trim() === '' ||
			!headersComplete ||
			(body === 'template' && template.trim() === '') ||
			!(Number.isInteger(openTasks) && openTasks >= 1 && openTasks <= 64) ||
			!callMinutesValid
	);

	function headerBody() {
		return headers.map((header) =>
			header.value === ''
				? { name: header.name.trim() }
				: { name: header.name.trim(), value: header.value }
		);
	}

	/** Saved: on to the webhook's page, once a new secret was seen. */
	function done(id: string, newSecret: string | null) {
		if (newSecret) {
			savedId = id;
			secret = { webhook: name.trim(), value: newSecret };
		} else {
			ondone(id);
		}
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
			let newSecret: string | null = null;
			if (signed && !webhook.signed)
				newSecret = (await unwrap(api.POST('/api/v1/webhooks/{id}/secret', path))).secret;
			if (!signed && webhook.signed) await unwrap(api.DELETE('/api/v1/webhooks/{id}/secret', path));
			toast.success(m.webhook_saved());
			done(webhook.id, newSecret);
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
			toast.success(m.webhook_saved());
			done(created.id, created.secret);
		}
	}
</script>

<AsyncForm class="flex max-w-3xl flex-col gap-6" action={save} ondone={() => {}}>
	{#snippet children({ busy, error })}
		<Field.Field>
			<Field.Label for="wh-name">{m.field_name()}</Field.Label>
			<Input id="wh-name" bind:value={name} maxlength={100} required />
		</Field.Field>
		<Field.Field>
			<HintLabel
				for="wh-url"
				label={m.webhook_url()}
				hint={m.webhook_url_hint()}
				hintId="wh-url-hint"
			/>
			<Input
				id="wh-url"
				type="url"
				bind:value={url}
				maxlength={2000}
				required
				aria-describedby="wh-url-hint"
			/>
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
		<fieldset class="flex flex-col gap-2" aria-labelledby="wh-headers-label">
			<div class="mb-1 flex items-center gap-1">
				<span id="wh-headers-label" class="text-sm font-medium">{m.webhook_headers()}</span>
				<InfoHint text={m.webhook_headers_hint()} about={m.webhook_headers()} />
			</div>
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
					<IconButton
						type="button"
						label={m.webhook_header_remove({ name: header.name })}
						onclick={() => headers.splice(index, 1)}
					>
						<Trash2 aria-hidden="true" />
					</IconButton>
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
		</fieldset>
		<Field.Field>
			<HintLabel
				for="wh-open-tasks"
				label={m.webhook_open_tasks()}
				hint={m.webhook_open_tasks_hint()}
				hintId="wh-open-tasks-hint"
			/>
			<Input
				id="wh-open-tasks"
				type="number"
				min={1}
				max={64}
				step={1}
				class="max-w-32"
				bind:value={openTasks}
				required
				aria-describedby="wh-open-tasks-hint wh-open-tasks-rule"
			/>
			<Field.Description id="wh-open-tasks-rule">{m.webhook_open_tasks_rule()}</Field.Description>
		</Field.Field>
		{#if showsModelCall}
			<div class="flex flex-wrap items-end gap-3">
				<Field.Field class="min-w-48 flex-1">
					<HintLabel
						for="wh-model-call"
						label={m.webhook_model_call()}
						hint={m.webhook_model_call_hint()}
						hintId="wh-model-call-hint"
					/>
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
		{/if}
		<div class="flex items-center gap-1">
			<Choice bind:checked={signed} aria-describedby="wh-signed-hint" class="font-medium">
				{m.webhook_signed()}
			</Choice>
			<InfoHint text={m.webhook_signed_hint()} about={m.webhook_signed()} id="wh-signed-hint" />
		</div>
		<Choice bind:checked={active} class="font-medium">{m.webhook_active()}</Choice>
		<div class="flex flex-col gap-3 border-t pt-4">
			{#if error}<Field.Error>{error}</Field.Error>{/if}
			<div class="flex flex-wrap justify-end gap-2">
				<a href={cancelHref} class={cn(buttonVariants({ variant: 'ghost' }))}>{m.cancel()}</a>
				<Button type="submit" disabled={busy || incomplete}>
					{webhook ? m.save() : m.create()}
				</Button>
			</div>
		</div>
	{/snippet}
</AsyncForm>

<SecretDialog
	secret={secret?.value ?? null}
	title={m.webhook_secret_title({ name: secret?.webhook ?? '' })}
	description={m.webhook_secret_hint()}
	onclose={() => {
		secret = null;
		if (savedId) ondone(savedId);
	}}
/>
