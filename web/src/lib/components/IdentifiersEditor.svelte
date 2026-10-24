<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Plus from '@lucide/svelte/icons/plus';
	import SearchIcon from '@lucide/svelte/icons/search';
	import X from '@lucide/svelte/icons/x';
	import { tick } from 'svelte';
	import InfoHint from '#lib/components/InfoHint.svelte';
	import Select from '#lib/components/Select.svelte';
	import TagChip from '#lib/components/TagChip.svelte';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { api } from '#lib/api/client.ts';
	import {
		IDENTIFIER_KINDS,
		type IdentifierKind,
		type IdentifierRow,
		type IdentifierSource,
		kindLabel,
		NAMING_KINDS,
		row
	} from '#lib/identifiers.ts';
	import {
		type Contact,
		type Tag,
		userChoice,
		userName,
		type UserName
	} from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { phone } from '#lib/phone.svelte.ts';
	import { pathLabel } from '#lib/tags.ts';

	// A contact's identifiers, one line each under their kind (Tobi, 20.10.2026): the value, a
	// mark if learned or rejected, the topic it points to. A line opens with its arrow, one at a
	// time (`opened`): one entered by hand shows kind, value and topic, changed at once (saved
	// with the editor); a learned one can be taken over (then it is entered by hand) or
	// rejected (training does not learn it again); a rejected one can be allowed again. Enter
	// in the value closes the line. A search finds them by value, kind and topic; a new one
	// opens empty. `errors` (by row key) show in their open line. `kinds`: those offered (a
	// person's in the profile); `withUsers`: a customer or personnel number may name the user it
	// belongs to (the contact dialog). `contacts`: the lines are a user's numbers at these
	// contacts (the profile, issue #82): each names its contact, offers the topics that contact
	// enables, and a learned one is taken over or declined as not theirs.
	let {
		rows = $bindable(),
		topics = [],
		opened = $bindable(null),
		errors = {},
		hint,
		kinds: offered = IDENTIFIER_KINDS,
		withUsers = false,
		contacts
	}: {
		rows: IdentifierRow[];
		topics?: readonly Tag[];
		opened?: number | null;
		errors?: Record<number, string>;
		/** The help of the identifiers, behind an info button beside the search. */
		hint?: string;
		kinds?: readonly IdentifierKind[];
		withUsers?: boolean;
		contacts?: readonly Pick<Contact, 'id' | 'name' | 'topic_ids'>[];
	} = $props();

	const uid = $props.id();
	let query = $state('');
	let users = $state<UserName[]>([]);
	const kinds = $derived(offered.map((kind) => ({ value: kind, label: kindLabel(kind) })));
	const userOptions = $derived([
		{ value: '', label: m.identifier_user_none() },
		...users.map((user) => ({ value: user.id, label: userChoice(user) }))
	]);

	$effect(() => {
		if (!withUsers) return;
		// Without the list, a number still shows whose it is by id; it only cannot be chosen.
		void api
			.GET('/api/v1/users')
			.then(({ data }) => {
				if (Array.isArray(data)) users = data;
			})
			.catch(() => {});
	});
	const contactOptions = $derived([
		{ value: '', label: m.number_contact_choose() },
		...(contacts ?? []).map((contact) => ({ value: contact.id, label: contact.name }))
	]);
	const compact = (text: string) => text.replace(/\s+/g, '').toLocaleLowerCase();
	const shown = $derived.by(() => {
		const wanted = compact(query);
		if (wanted === '') return rows;
		return rows.filter((item) =>
			compact(
				`${item.value} ${kindLabel(item.kind)} ${topicOf(item.topic_id)?.name ?? ''} ${
					contactOf(item)?.name ?? ''
				}`
			).includes(wanted)
		);
	});
	const groups = $derived(
		offered
			.map((kind) => ({
				kind,
				rows: shown.filter((item) => item.kind === kind)
			}))
			.filter((group) => group.rows.length > 0)
	);

	function topicOf(id: string): Tag | null {
		return topics.find((topic) => topic.id === id) ?? null;
	}

	function contactOf(item: IdentifierRow): Pick<Contact, 'id' | 'name' | 'topic_ids'> | null {
		return contacts?.find((contact) => contact.id === item.contact_id) ?? null;
	}

	/** The topics a line may point to: those its contact enables, for a user's number. */
	function topicsFor(item: IdentifierRow): readonly Tag[] {
		if (!contacts) return topics;
		const enabled = contactOf(item)?.topic_ids ?? [];
		return topics.filter((topic) => enabled.includes(topic.id));
	}

	function topicChoices(item: IdentifierRow) {
		const own = topicsFor(item);
		const options = [
			{ value: '', label: m.topic_none() },
			...own.map((topic) => ({ value: topic.id, label: pathLabel(topic) }))
		];
		return item.topic_id === '' || own.some((topic) => topic.id === item.topic_id)
			? options
			: [...options, { value: item.topic_id, label: m.topic_not_enabled() }];
	}

	function indexOf(item: IdentifierRow): number {
		return rows.findIndex((other) => other.key === item.key);
	}

	function become(item: IdentifierRow, source: IdentifierSource) {
		rows = rows.map((other) => (other.key === item.key ? { ...other, source } : other));
	}

	function drop(item: IdentifierRow) {
		rows = rows.filter((other) => other.key !== item.key);
		if (opened === item.key) opened = null;
	}

	async function add() {
		const fresh = row(offered[0]);
		query = '';
		rows = [...rows, fresh];
		opened = fresh.key;
		await tick();
		document.getElementById(`${uid}-${fresh.key}-value`)?.focus();
	}

	function closeOnEnter(event: KeyboardEvent) {
		if (event.key !== 'Enter') return;
		// Not the editor's form: Enter only closes the line.
		event.preventDefault();
		opened = null;
	}
</script>

<div class="flex flex-col gap-1" role="group" aria-label={m.master_identifiers()}>
	<div class="flex items-center gap-2 pb-1">
		<label
			class="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-full border border-input bg-card px-3.5 text-muted-foreground focus-within:border-ring sm:h-10 dark:bg-input/30"
		>
			<SearchIcon class="size-4 shrink-0" aria-hidden="true" />
			<input
				type="search"
				bind:value={query}
				placeholder={m.identifier_search()}
				aria-label={m.identifier_search()}
				class="h-full min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
			/>
		</label>
		{#if hint}<InfoHint text={hint} about={m.master_identifiers()} />{/if}
		{#if phone.current}
			<Button
				type="button"
				size="icon"
				class="size-11 shrink-0"
				aria-label={m.identifier_add()}
				onclick={add}
			>
				<Plus class="size-5" aria-hidden="true" />
			</Button>
		{:else}
			<Button type="button" variant="outline" class="h-10 shrink-0" onclick={add}>
				<Plus aria-hidden="true" />
				{m.identifier_add_short()}
			</Button>
		{/if}
	</div>

	{#if rows.length === 0}
		<p class="rounded-2xl border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
			{m.identifier_none()}
		</p>
	{:else if groups.length === 0}
		<p class="px-1 py-2 text-sm text-muted-foreground">{m.assignment_none_found()}</p>
	{/if}

	{#each groups as group (group.kind)}
		<h3
			class="flex items-baseline gap-2 px-1 pt-2 pb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase"
		>
			{kindLabel(group.kind)}
			<span class="font-medium tabular-nums">{group.rows.length}</span>
		</h3>
		<ul class="divide-y overflow-hidden rounded-2xl border bg-card">
			{#each group.rows as item (item.key)}
				{@const open = opened === item.key}
				{@const topic = topicOf(item.topic_id)}
				{@const index = indexOf(item)}
				<li>
					<div class={['flex items-center gap-1 pr-1', open && 'bg-secondary/60']}>
						<button
							type="button"
							class="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 py-1.5 pl-3 text-left"
							aria-expanded={open}
							aria-controls={open ? `${uid}-${item.key}` : undefined}
							onclick={() => (opened = open ? null : item.key)}
						>
							<ChevronRight
								class={[
									'size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none',
									open && 'rotate-90 text-foreground'
								]}
								aria-hidden="true"
							/>
							{#if contacts}
								<span class="max-w-[40%] shrink-0 truncate text-sm">
									{contactOf(item)?.name ?? m.number_contact_none()}
								</span>
							{/if}
							<span
								class={[
									'min-w-0 flex-1 truncate',
									item.value ? 'font-mono text-sm' : 'text-sm text-muted-foreground',
									item.source === 'rejected' && 'text-muted-foreground line-through'
								]}
							>
								{item.value || m.identifier_new()}
							</span>
							{#if item.source !== 'manual'}
								<Badge variant={item.source === 'learned' ? 'secondary' : 'outline'}>
									{item.source === 'learned' ? m.identifier_learned() : m.identifier_rejected()}
								</Badge>
							{/if}
							{#if topic}<TagChip tag={topic} topic size="sm" />{/if}
							{#if withUsers && item.user_id}
								<Badge variant="outline">{userName(users, item.user_id)}</Badge>
							{/if}
							{#if errors[item.key]}
								<span class="size-[7px] shrink-0 rounded-full bg-destructive" aria-hidden="true"
								></span>
							{/if}
						</button>
						{#if item.source === 'manual'}
							<Button
								type="button"
								variant="ghost"
								size="icon"
								class="size-9 shrink-0"
								aria-label={m.identifier_remove_named({ value: item.value || m.identifier_new() })}
								onclick={() => drop(item)}
							>
								<X aria-hidden="true" />
							</Button>
						{:else}
							<span class="size-9 shrink-0" aria-hidden="true"></span>
						{/if}
					</div>
					{#if open}
						<div id="{uid}-{item.key}" class="border-t bg-secondary/30 px-3 py-3 sm:pl-10">
							{#if item.source === 'manual'}
								{#if contacts}
									<div class="mb-2 grid items-center gap-2 sm:grid-cols-[12.5rem_minmax(0,1fr)]">
										<span class="text-sm text-muted-foreground">{m.number_contact()}</span>
										<Select
											bind:value={rows[index].contact_id}
											options={contactOptions}
											aria-label={m.number_contact()}
											class="h-10"
										/>
									</div>
								{/if}
								{@const ownTopics = topicsFor(item)}
								<div
									class={[
										'grid gap-2',
										ownTopics.length > 0 || item.topic_id !== ''
											? 'sm:grid-cols-[12.5rem_minmax(0,1fr)_9.5rem]'
											: 'sm:grid-cols-[12.5rem_minmax(0,1fr)]'
									]}
								>
									<Select
										bind:value={rows[index].kind}
										options={kinds}
										aria-label={m.identifier_kind()}
										class="h-10"
									/>
									<Input
										id="{uid}-{item.key}-value"
										bind:value={rows[index].value}
										aria-label={m.identifier_value()}
										aria-invalid={errors[item.key] ? true : undefined}
										maxlength={100}
										class="h-10 font-mono"
										onkeydown={closeOnEnter}
									/>
									{#if ownTopics.length > 0 || item.topic_id !== ''}
										<Select
											bind:value={rows[index].topic_id}
											options={topicChoices(item)}
											aria-label={m.identifier_topic()}
											class="h-10"
										/>
									{/if}
								</div>
								{#if withUsers && NAMING_KINDS.includes(item.kind)}
									<div class="mt-2 grid items-center gap-2 sm:grid-cols-[12.5rem_minmax(0,1fr)]">
										<span class="text-sm text-muted-foreground">{m.identifier_user()}</span>
										<Select
											bind:value={rows[index].user_id}
											options={userOptions}
											aria-label={m.identifier_user()}
											class="h-10"
										/>
									</div>
								{/if}
								{#if errors[item.key]}
									<p class="mt-2 text-sm text-destructive" role="alert">{errors[item.key]}</p>
								{/if}
							{:else}
								<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
									<p class="min-w-48 flex-1 text-sm text-muted-foreground">
										{#if contacts}
											{item.source === 'learned'
												? m.number_learned_note()
												: m.number_declined_note()}
										{:else}
											{item.source === 'learned'
												? m.identifier_learned_note()
												: m.identifier_rejected_note()}
										{/if}
									</p>
									{#if item.source === 'learned'}
										<Button
											type="button"
											variant="outline"
											size="sm"
											onclick={() => become(item, 'manual')}
										>
											{m.identifier_keep()}
										</Button>
										<Button
											type="button"
											variant="outline"
											size="sm"
											onclick={() => become(item, 'rejected')}
										>
											{contacts ? m.number_not_mine() : m.identifier_reject()}
										</Button>
									{:else if contacts}
										<Button
											type="button"
											variant="outline"
											size="sm"
											onclick={() => become(item, 'learned')}
										>
											{m.number_undo()}
										</Button>
									{:else}
										<Button type="button" variant="outline" size="sm" onclick={() => drop(item)}>
											{m.identifier_unblock()}
										</Button>
									{/if}
								</div>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/each}
</div>
