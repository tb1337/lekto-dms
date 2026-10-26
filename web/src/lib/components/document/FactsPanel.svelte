<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import Copy from '@lucide/svelte/icons/copy';
	import Pin from '@lucide/svelte/icons/pin';
	import ScanQrCode from '@lucide/svelte/icons/scan-qr-code';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import UserCheck from '@lucide/svelte/icons/user-check';
	import UsersIcon from '@lucide/svelte/icons/users';
	import { untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import { copyText } from '#lib/clipboard.ts';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import CodeThumb from '#lib/components/document/CodeThumb.svelte';
	import SourceChip from '#lib/components/document/SourceChip.svelte';
	import Select from '#lib/components/Select.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { reportError } from '#lib/errors.ts';
	import {
		codeSpans,
		evidenceLabel,
		grouped,
		identifierKey,
		roleLabel,
		shown,
		strengthLabel,
		type CodeFacts,
		type CodePlace,
		type DocumentNumber,
		type Facts,
		type FoundIdentifier,
		type FoundPerson,
		type NamedContact,
		type Span
	} from '#lib/facts.ts';
	import { formatMoney } from '#lib/i18n.ts';
	import { kindLabel } from '#lib/identifiers.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { masterDataDialogs } from '#lib/masterdata-dialog.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { pathLabel, tagOptions } from '#lib/tags.ts';
	import { cn } from '#lib/utils.ts';

	// The facts beside the text: what supports the document's contact, what speaks of other
	// contacts, the identifiers of no contact (admins attach them, with a topic of the contact,
	// the document's by default), and the codes on the pages. Hovering or focusing an entry
	// marks it in the text and on the pages; a click keeps the mark. A contact named here
	// shows its logo, and for admins it opens its editor (Tobi, 20.10.2026), also the other
	// contacts whose documents show an identifier.
	let {
		facts,
		documentId,
		lookup,
		topicId = null,
		admin,
		onmark,
		onshowcode,
		onchanged
	}: {
		facts: Facts;
		documentId: string;
		lookup: Lookup | null;
		/** The document's topic: an identifier attached points to it, if the contact has it. */
		topicId?: string | null;
		/** Admins attach identifiers (they are master data). */
		admin: boolean;
		/** The spans to mark in the text and on the pages under `label`, none to mark nothing;
		 * `reveal` after a click. */
		onmark: (spans: Span[], reveal: boolean, label: string) => void;
		/** Show a code where it stands on its page. */
		/** Show the code on one of its pages, all its places marked. */
		onshowcode: (code: CodeFacts, place: CodePlace) => void;
		/** After an identifier was attached. */
		onchanged: () => void;
	} = $props();

	type Entry = NamedContact | FoundIdentifier;

	let hover = $state<string | null>(null);
	let pinned = $state<string | null>(null);
	let attaching = $state<string | null>(null);
	let target = $state<'document' | 'other'>('document');
	let other = $state('');
	let attachTopic = $state('');
	let busy = $state(false);
	// A click keeps a mark: the text scrolls to it (also when the entry was marked already).
	let reveal = false;
	let clicks = $state(0);

	const groups = $derived(grouped(facts));
	const contacts = $derived(lookup?.contacts ?? []);
	const contactOf = (id: string | null | undefined) =>
		contacts.find((contact) => contact.id === id) ?? null;
	const contactName = (id: string | null | undefined) => contactOf(id)?.name ?? '…';
	const documentContact = $derived(facts.contact_id ? contactName(facts.contact_id) : null);
	const active = $derived(hover ?? pinned);
	// The topics of the contact an identifier goes to; the document's topic first of all.
	const attachContact = $derived(target === 'document' ? facts.contact_id : other);
	const attachTopics = $derived.by(() => {
		const enabled = contacts.find((contact) => contact.id === attachContact)?.topic_ids ?? [];
		return tagOptions(lookup?.tags ?? [], 'topic').filter((option) =>
			enabled.includes(option.value)
		);
	});
	$effect(() => {
		const options = attachTopics;
		untrack(() => {
			if (options.some((option) => option.value === attachTopic)) return;
			const own = options.some((option) => option.value === topicId);
			attachTopic = own && topicId ? topicId : '';
		});
	});
	const topicName = (id: string | null | undefined) => {
		const tag = lookup?.tags.find((entry) => entry.id === id);
		return tag ? pathLabel(tag) : null;
	};

	const entryId = (entry: Entry) =>
		'kind' in entry ? `id:${identifierKey(entry)}` : `name:${entry.contact_id}`;
	const codeId = (index: number) => `code:${index}`;
	const personId = (person: FoundPerson) => `person:${person.user_id}`;
	const numberId = (number: DocumentNumber) => `number:${number.kind}:${number.value}`;

	$effect(() => {
		const id = active;
		void clicks;
		const scroll = reveal;
		reveal = false;
		if (id === null) {
			onmark([], false, '');
			return;
		}
		if (id.startsWith('code:')) {
			const code = facts.codes?.[Number(id.slice(5))];
			onmark(code ? codeSpans(facts, code) : [], scroll, code?.format ?? '');
			return;
		}
		if (id.startsWith('person:')) {
			const person = facts.persons?.find((item) => personId(item) === id);
			onmark(person?.spans ?? [], scroll, person?.name ?? '');
			return;
		}
		if (id.startsWith('number:')) {
			const number = facts.numbers?.find((item) => numberId(item) === id);
			onmark(number?.spans ?? [], scroll, number ? kindLabel(number.kind) : '');
			return;
		}
		const entry = [...facts.named, ...facts.identifiers].find((item) => entryId(item) === id);
		onmark(entry?.spans ?? [], scroll, entry ? entryLabel(entry) : '');
	});

	/** What a mark of the entry on the page says: the kind of an identifier, a contact's name. */
	function entryLabel(entry: Entry): string {
		return 'kind' in entry
			? kindLabel(entry.kind)
			: (contactOf(entry.contact_id)?.name ?? entry.name);
	}

	function pin(id: string) {
		pinned = pinned === id ? null : id;
		reveal = pinned !== null;
		clicks += 1;
	}

	function startAttach(item: FoundIdentifier) {
		const id = entryId(item);
		attaching = attaching === id ? null : id;
		target = facts.contact_id ? 'document' : 'other';
		other = '';
		attachTopic = topicId ?? '';
	}

	async function attach(item: FoundIdentifier) {
		const contact = target === 'document' ? facts.contact_id : other;
		if (!contact) return;
		busy = true;
		try {
			await unwrap(
				api.POST('/api/v1/contacts/{id}/identifiers', {
					params: { path: { id: contact } },
					body: {
						kind: item.kind,
						value: item.value,
						...(attachTopic ? { topic_id: attachTopic } : {})
					}
				})
			);
			toast.success(
				m.facts_attach_done({ kind: kindLabel(item.kind), contact: contactName(contact) })
			);
			attaching = null;
			onchanged();
		} catch (error) {
			reportError(error);
		} finally {
			busy = false;
		}
	}

	const copy = (text: string) => copyText(text);

	const fieldName = (id: string) => lookup?.fields.find((field) => field.id === id)?.name ?? '…';
	// The contact an IBAN of a code belongs to, as the identifiers of the facts say.
	const ibanContact = (iban: string) =>
		facts.identifiers.find(
			(item) => item.kind === 'iban' && item.value === iban.replace(/\s+/g, '').toUpperCase()
		)?.contact_id ?? null;
</script>

{#snippet contactLink(id: string)}
	{@const contact = contactOf(id)}
	{#if admin}
		<!-- Admins change the contact right here: its dialog opens over the page. -->
		<button
			type="button"
			class="inline-flex max-w-full min-w-0 cursor-pointer items-center gap-1.5 font-medium text-foreground underline-offset-2 hover:underline"
			title={m.facts_contact_open()}
			onclick={() => masterDataDialogs.open('contacts', id)}
		>
			<ContactAvatar contact={contact ?? { name: '…' }} size="xs" />
			<span class="truncate">{contact?.name ?? '…'}</span>
		</button>
	{:else}
		<span class="inline-flex max-w-full min-w-0 items-center gap-1.5 font-medium text-foreground">
			<ContactAvatar contact={contact ?? { name: '…' }} size="xs" />
			<span class="truncate">{contact?.name ?? '…'}</span>
		</span>
	{/if}
{/snippet}

{#snippet entryRow(entry: Entry, contactId: string | null)}
	{@const id = entryId(entry)}
	{@const identifier = 'kind' in entry ? entry : null}
	{@const named = 'kind' in entry ? null : entry}
	<div
		class={cn('rounded-xl transition-colors', active === id && 'bg-panel')}
		onmouseenter={() => (hover = id)}
		onmouseleave={() => (hover = null)}
		role="presentation"
	>
		<div class="flex items-center gap-2 px-2.5 py-2">
			<button
				type="button"
				class="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left"
				aria-pressed={pinned === id}
				onclick={() => pin(id)}
				onfocus={() => (hover = id)}
				onblur={() => (hover = null)}
			>
				<span class="text-xs font-medium text-muted-foreground">
					{identifier
						? kindLabel(identifier.kind)
						: named?.alias
							? m.facts_alias()
							: m.facts_name()}
					{#if identifier}
						<span class="font-normal">· {roleLabel(identifier.role)}</span>
					{/if}
				</span>
				<span class={cn('text-sm break-words', identifier && 'font-mono text-[13px]')}>
					{identifier ? shown(identifier) : named?.name}
				</span>
				{#if identifier?.topic_id && topicName(identifier.topic_id)}
					<span class="text-xs text-muted-foreground">
						{m.facts_topic({ topic: topicName(identifier.topic_id) ?? '' })}
					</span>
				{/if}
				{#if entry.in_code}
					<span class="text-xs text-muted-foreground">
						{entry.in_text ? m.facts_in_code() : m.facts_only_in_code()}
					</span>
				{/if}
			</button>
			{#if identifier && !identifier.contact_id && admin}
				<!-- Only the pin: the label would repeat on every line. -->
				<Button
					variant="outline"
					size="icon"
					class="size-8 shrink-0"
					aria-label={m.facts_attach_value({ value: shown(identifier) })}
					title={m.facts_attach()}
					aria-expanded={attaching === id}
					onclick={() => startAttach(identifier)}
				>
					<Pin aria-hidden="true" />
				</Button>
			{/if}
		</div>
		{#if contactId}
			<div class="-mt-1 flex px-2.5 pb-2 text-xs">{@render contactLink(contactId)}</div>
		{/if}
		{#if identifier && identifier.other_contacts}
			<div class="-mt-1 flex items-start gap-1.5 px-2.5 pb-2 text-xs text-lane-yellow-foreground">
				<TriangleAlert class="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
				{#if identifier.other_contact_ids?.length}
					<span class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
						{m.facts_other_contacts_of()}
						{#each identifier.other_contact_ids as other (other)}
							{@render contactLink(other)}
						{/each}
					</span>
				{:else}
					{identifier.other_contacts === 1
						? m.facts_other_contacts_one()
						: m.facts_other_contacts({ count: identifier.other_contacts })}
				{/if}
			</div>
		{/if}
		{#if identifier && attaching === id}
			<form
				class="mx-2.5 mb-2.5 flex flex-col gap-2.5 rounded-xl border bg-card p-3"
				onsubmit={(event) => {
					event.preventDefault();
					void attach(identifier);
				}}
			>
				<span class="text-sm font-medium">
					{m.facts_attach_title({ kind: kindLabel(identifier.kind) })}
				</span>
				{#if facts.contact_id}
					<label class="flex items-start gap-2.5 text-sm">
						<input
							type="radio"
							name="attach-target"
							value="document"
							bind:group={target}
							class="mt-1 accent-primary"
						/>
						<span class="flex flex-col">
							<span class="inline-flex items-center gap-1.5">
								<ContactAvatar contact={contactOf(facts.contact_id) ?? { name: '…' }} size="xs" />
								{documentContact}
							</span>
							<span class="text-xs text-muted-foreground">{m.facts_attach_document_contact()}</span>
						</span>
					</label>
				{/if}
				<label class="flex items-center gap-2.5 text-sm">
					<input
						type="radio"
						name="attach-target"
						value="other"
						bind:group={target}
						class="accent-primary"
					/>
					{m.facts_attach_other()}
				</label>
				{#if target === 'other'}
					<Select
						bind:value={other}
						aria-label={m.facts_attach_other()}
						options={[
							{ value: '', label: m.facts_attach_pick() },
							...contacts.map((contact) => ({ value: contact.id, label: contact.name }))
						]}
					/>
				{/if}
				{#if attachTopics.length > 0}
					<label class="flex flex-col gap-1 text-sm">
						<span class="text-xs text-muted-foreground">{m.facts_attach_topic()}</span>
						<Select
							bind:value={attachTopic}
							aria-label={m.facts_attach_topic()}
							options={[{ value: '', label: m.topic_none() }, ...attachTopics]}
						/>
					</label>
				{/if}
				<span class="text-xs text-muted-foreground">{m.facts_attach_hint()}</span>
				<div class="flex justify-end gap-2">
					<Button type="button" variant="ghost" size="sm" onclick={() => (attaching = null)}>
						{m.cancel()}
					</Button>
					<Button
						type="submit"
						size="sm"
						disabled={busy || (target === 'other' ? !other : !facts.contact_id)}
					>
						{m.facts_attach()}
					</Button>
				</div>
			</form>
		{/if}
	</div>
{/snippet}

<div class="flex flex-col gap-3.5">
	<section aria-labelledby="facts-title" class="rounded-2xl border bg-card p-3.5">
		<div class="flex items-baseline gap-2 px-1 pb-1">
			<h2 id="facts-title" class="text-[15px] font-semibold">{m.facts_title()}</h2>
			<span class="text-xs text-muted-foreground"
				>{phone.current ? m.facts_hint_phone() : m.facts_hint()}</span
			>
		</div>
		{#if groups.own.length + groups.others.length + groups.unknown.length === 0}
			<p class="px-1 py-2 text-sm text-muted-foreground">{m.facts_none()}</p>
		{/if}
		{#if groups.own.length > 0}
			<h3
				class="mt-2 flex items-center gap-1.5 px-1 text-xs font-semibold text-lane-green-foreground"
			>
				<UserCheck class="size-3.5" aria-hidden="true" />
				{m.facts_own()}
				{#if facts.contact_id}{@render contactLink(facts.contact_id)}{/if}
			</h3>
			{#each groups.own as entry (entryId(entry))}
				{@render entryRow(entry, null)}
			{/each}
		{/if}
		{#if groups.others.length > 0}
			<h3 class="mt-3 px-1 text-xs font-semibold text-muted-foreground">{m.facts_others()}</h3>
			{#each groups.others as entry (entryId(entry))}
				{@render entryRow(entry, entry.contact_id)}
			{/each}
		{/if}
		{#if groups.unknown.length > 0}
			<h3 class="mt-3 px-1 text-xs font-semibold text-muted-foreground">{m.facts_unknown()}</h3>
			<p class="px-1 text-xs text-muted-foreground">
				{admin ? m.facts_unknown_hint() : m.facts_attach_admins()}
			</p>
			{#each groups.unknown as entry (entryId(entry))}
				{@render entryRow(entry, null)}
			{/each}
		{/if}
	</section>

	{#if facts.numbers && facts.numbers.length > 0}
		<!-- The document's own numbers, a strand's, another document's it refers to (#145). -->
		<section aria-labelledby="numbers-title" class="rounded-2xl border bg-card p-3.5">
			<div class="flex items-baseline gap-2 px-1 pb-1">
				<h2 id="numbers-title" class="text-[15px] font-semibold">{m.facts_numbers()}</h2>
				<span class="text-xs text-muted-foreground">{m.facts_numbers_hint()}</span>
			</div>
			{#each facts.numbers as number (numberId(number))}
				{@const id = numberId(number)}
				<div
					class={cn('rounded-xl transition-colors', active === id && 'bg-panel')}
					onmouseenter={() => (hover = id)}
					onmouseleave={() => (hover = null)}
					role="presentation"
				>
					<button
						type="button"
						class="flex w-full min-w-0 flex-col items-start gap-0.5 px-2.5 py-2 text-left"
						aria-pressed={pinned === id}
						onclick={() => pin(id)}
						onfocus={() => (hover = id)}
						onblur={() => (hover = null)}
					>
						<span class="text-xs font-medium text-muted-foreground">
							{kindLabel(number.kind)}
							<span class="font-normal">· {roleLabel(number.role)}</span>
						</span>
						<span class="font-mono text-[13px] break-words">{number.written ?? number.value}</span>
					</button>
				</div>
			{/each}
		</section>
	{/if}

	{#if facts.persons && facts.persons.length > 0}
		<section aria-labelledby="persons-title" class="rounded-2xl border bg-card p-3.5">
			<div class="flex items-baseline gap-2 px-1 pb-1">
				<h2 id="persons-title" class="text-[15px] font-semibold">
					<UsersIcon
						class="mr-1 inline-block size-4 align-[-0.15em]"
						aria-hidden="true"
					/>{m.facts_persons()}
				</h2>
				<span class="text-xs text-muted-foreground">{m.facts_persons_hint()}</span>
			</div>
			{#each facts.persons as person (person.user_id)}
				{@const id = personId(person)}
				<div
					class={cn('rounded-xl transition-colors', active === id && 'bg-panel')}
					onmouseenter={() => (hover = id)}
					onmouseleave={() => (hover = null)}
					role="presentation"
				>
					<button
						type="button"
						class="flex w-full min-w-0 flex-col items-start gap-0.5 px-2.5 py-2 text-left"
						aria-pressed={pinned === id}
						onclick={() => pin(id)}
						onfocus={() => (hover = id)}
						onblur={() => (hover = null)}
					>
						<span class="text-xs font-medium text-muted-foreground">
							{strengthLabel(person.strength)}
						</span>
						<span class="text-sm break-words">{person.name}</span>
						<span class="text-xs text-muted-foreground">
							{person.evidence.map(evidenceLabel).join(' · ')}
						</span>
					</button>
				</div>
			{/each}
		</section>
	{/if}

	<section aria-labelledby="codes-title" class="rounded-2xl border bg-card p-3.5">
		<div class="flex items-baseline gap-2 px-1 pb-1">
			<!-- The icon in the line of text: the heading keeps the baseline of the hint beside it. -->
			<h2 id="codes-title" class="text-[15px] font-semibold">
				<ScanQrCode
					class="mr-1 inline-block size-4 align-[-0.15em]"
					aria-hidden="true"
				/>{m.codes_title()}
			</h2>
			<span class="text-xs text-muted-foreground">{m.codes_hint()}</span>
		</div>
		{#if facts.codes === null}
			<p class="px-1 py-2 text-sm text-muted-foreground">{m.codes_unread()}</p>
		{:else if facts.codes.length === 0}
			<p class="px-1 py-2 text-sm text-muted-foreground">{m.codes_none()}</p>
		{:else}
			{#each facts.codes as code, index (index)}
				{@const id = codeId(index)}
				<div
					class={cn('flex gap-3 rounded-xl p-2.5 transition-colors', active === id && 'bg-panel')}
					onmouseenter={() => (hover = id)}
					onmouseleave={() => (hover = null)}
					role="presentation"
				>
					<button
						type="button"
						class="shrink-0 self-start rounded-lg"
						aria-label={m.codes_mark({ format: code.format })}
						aria-pressed={pinned === id}
						onclick={() => pin(id)}
						onfocus={() => (hover = id)}
						onblur={() => (hover = null)}
					>
						<CodeThumb {documentId} {code} />
					</button>
					<div class="flex min-w-0 flex-1 flex-col gap-1.5">
						<div class="flex flex-wrap items-center gap-2">
							<span class="text-sm font-medium">{code.giro ? m.code_giro() : code.format}</span>
							{#if code.giro}
								<span
									class="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
								>
									{m.code_giro_badge({ format: code.format })}
								</span>
							{/if}
							<!-- One code however often it is printed: a chip per page, as at a field. -->
							<span class="ml-auto flex flex-wrap justify-end gap-1">
								{#each code.places as place (place.page)}
									<SourceChip {place} onjump={() => onshowcode(code, place)} />
								{/each}
							</span>
						</div>
						{#if code.giro}
							<dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[13px]">
								<dt class="text-muted-foreground">{m.code_giro_name()}</dt>
								<dd>{code.giro.name}</dd>
								{#if ibanContact(code.giro.iban)}
									<dt class="text-muted-foreground">{m.field_contact()}</dt>
									<dd class="flex min-w-0">{@render contactLink(ibanContact(code.giro.iban)!)}</dd>
								{/if}
								<dt class="text-muted-foreground">{m.identifier_kind_iban()}</dt>
								<dd class="font-mono text-xs break-words">
									{shown({ kind: 'iban', value: code.giro.iban })}
								</dd>
								{#if code.giro.bic}
									<dt class="text-muted-foreground">{m.code_giro_bic()}</dt>
									<dd class="font-mono text-xs">{code.giro.bic}</dd>
								{/if}
								{#if code.giro.amount}
									<dt class="text-muted-foreground">{m.code_giro_amount()}</dt>
									<dd class="flex flex-wrap items-center gap-1.5">
										{formatMoney(code.giro.amount.amount, code.giro.amount.currency)}
										{#each code.fields as field (field)}
											<span
												class="inline-flex items-center gap-1 rounded-full bg-lane-green px-2 py-0.5 text-[11px] font-medium text-lane-green-foreground"
											>
												<Check class="size-3" aria-hidden="true" />
												{m.code_same_as({ field: fieldName(field) })}
											</span>
										{/each}
									</dd>
								{/if}
								{#if code.giro.purpose}
									<dt class="text-muted-foreground">{m.code_giro_purpose()}</dt>
									<dd class="break-words">{code.giro.purpose}</dd>
								{/if}
							</dl>
						{:else}
							<div class="flex items-start gap-1 rounded-lg bg-surface py-1.5 pr-1 pl-2.5">
								<code
									class="max-h-24 min-w-0 flex-1 overflow-auto font-mono text-xs break-all whitespace-pre-wrap"
									>{code.text}</code
								>
								<Button
									variant="ghost"
									size="icon"
									class="size-7 shrink-0"
									aria-label={m.codes_copy()}
									onclick={() => copy(code.text)}
								>
									<Copy aria-hidden="true" />
								</Button>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		{/if}
	</section>
</div>
