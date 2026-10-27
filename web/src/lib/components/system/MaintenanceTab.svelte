<script lang="ts">
	import Play from '@lucide/svelte/icons/play';
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { api } from '#lib/api/client.ts';
	import { unwrap } from '#lib/api/call.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import LoadProblem from '#lib/components/LoadProblem.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { countOf, OPEN_STATES, type JobsSummary } from '#lib/jobs.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import Loading from '#lib/components/Loading.svelte';

	// The tab "Maintenance" of the page "System" (Tobi, 26.10.2026): what Lekto does by itself
	// for new documents, caught up on over the existing ones, one row each: name, the why and
	// how behind the info button, how many jobs of its kind wait or run, and for admins a
	// button that asks before it queues and then says how many were queued. Everyone sees the
	// rows and counts; the counts come every five seconds while the page is in view.
	interface Action {
		key: 'relate' | 'pages' | 'codes' | 'logos';
		name: string;
		info: string;
		confirm: string;
		/** The kind of the jobs it queues, counted from the summary. */
		kind: string;
		queue: () => Promise<number>;
		queued: (count: number) => string;
	}

	const POLL = 5_000;

	let summary = $state<JobsSummary | null>(null);
	let logoFetch = $state<boolean | null>(null);
	let problem = $state<string | null>(null);
	let asked = $state<Action | null>(null);
	let open = $state(false);

	const documents = (count: number) =>
		count === 1
			? m.maintenance_queued_document_one()
			: m.maintenance_queued_documents({ count: formatNumber(count) });
	const contacts = (count: number) =>
		count === 1
			? m.maintenance_queued_contact_one()
			: m.maintenance_queued_contacts({ count: formatNumber(count) });

	const ACTIONS: Action[] = [
		{
			key: 'relate',
			name: m.maintenance_relate_name(),
			info: m.maintenance_relate_info(),
			confirm: m.maintenance_relate_confirm(),
			kind: 'pipeline.relate',
			queue: async () => (await unwrap(api.POST('/api/v1/pipeline/relate'))).queued,
			queued: documents
		},
		{
			key: 'pages',
			name: m.maintenance_pages_name(),
			info: m.maintenance_pages_info(),
			confirm: m.maintenance_pages_confirm(),
			kind: 'pipeline.catch_up',
			queue: async () => (await unwrap(api.POST('/api/v1/pipeline/render-pages'))).queued,
			queued: documents
		},
		{
			key: 'codes',
			name: m.maintenance_codes_name(),
			info: m.maintenance_codes_info(),
			confirm: m.maintenance_codes_confirm(),
			kind: 'pipeline.facts',
			queue: async () => (await unwrap(api.POST('/api/v1/pipeline/read-codes'))).queued,
			queued: documents
		},
		{
			key: 'logos',
			name: m.maintenance_logos_name(),
			info: m.maintenance_logos_info(),
			confirm: m.maintenance_logos_confirm(),
			kind: 'contacts.logo',
			queue: async () => (await unwrap(api.POST('/api/v1/contacts/logos/fetch'))).queued,
			queued: contacts
		}
	];

	async function load() {
		try {
			summary = await unwrap(api.GET('/api/v1/jobs/summary'));
			problem = null;
		} catch (failure) {
			problem = describeError(failure);
		}
	}

	async function loadPipeline() {
		try {
			logoFetch = (await unwrap(api.GET('/api/v1/pipeline'))).logo_fetch;
		} catch {
			// The row shows without the note; the button answers 503 if fetching is off.
		}
	}

	onMount(() => {
		void load();
		void loadPipeline();
		const timer = setInterval(() => {
			if (document.visibilityState === 'visible') void load();
		}, POLL);
		return () => clearInterval(timer);
	});

	function ask(action: Action) {
		asked = action;
		open = true;
	}

	async function run() {
		if (!asked) return;
		const count = await asked.queue();
		toast.success(count === 0 ? m.maintenance_queued_none() : asked.queued(count));
		void load();
	}

	function waiting(kind: string): number {
		const item = summary?.kinds.find((entry) => entry.kind === kind);
		return item ? countOf(item, OPEN_STATES) : 0;
	}
</script>

<div class="flex flex-col gap-6">
	{#if problem && !summary}
		<LoadProblem {problem} onretry={load} />
	{:else if !summary}
		<Loading />
	{:else}
		<Card.Root as="section" size="flush" class="px-5 py-1 sm:px-6">
			<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3.5">
				<div class="flex items-center gap-1">
					<SectionTitle size="card">{m.maintenance_title()}</SectionTitle>
					<InfoTip label={m.hint_about({ name: m.maintenance_title() })} size="sm" class="w-80">
						<p>{m.maintenance_info()}</p>
					</InfoTip>
				</div>
				{#if !session.isAdmin}
					<span class="text-meta text-muted-foreground">{m.maintenance_admins_only()}</span>
				{/if}
			</div>
			<ul>
				{#each ACTIONS as action (action.key)}
					{@const count = waiting(action.kind)}
					{@const off = action.key === 'logos' && logoFetch === false}
					<li class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t py-3.5">
						<div class="flex min-w-0 flex-1 basis-56 items-center gap-1">
							<span class="font-medium">{action.name}</span>
							<InfoTip label={m.hint_about({ name: action.name })} size="sm" class="w-80">
								<p>{action.info}</p>
							</InfoTip>
						</div>
						<span class="text-meta text-muted-foreground tabular-nums">
							{count > 0
								? m.maintenance_waiting({ count: formatNumber(count) })
								: m.maintenance_waiting_none()}
						</span>
						{#if session.isAdmin}
							<div class="flex items-center gap-3">
								{#if off}
									<span class="text-meta text-muted-foreground">{m.maintenance_logos_off()}</span>
								{/if}
								<Button size="sm" variant="outline" disabled={off} onclick={() => ask(action)}>
									<Play aria-hidden="true" />{m.maintenance_run()}
								</Button>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		</Card.Root>
	{/if}
</div>

{#if asked}
	<ConfirmDialog
		bind:open
		title={m.maintenance_confirm_title({ name: asked.name })}
		description={asked.confirm}
		confirmLabel={m.maintenance_run()}
		destructive={false}
		onconfirm={run}
	/>
{/if}
