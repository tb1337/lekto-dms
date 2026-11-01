<script lang="ts">
	import MessageSquareCode from '@lucide/svelte/icons/message-square-code';
	import type { components } from '#lib/api/schema.ts';
	import FactRows from '#lib/components/document/FactRows.svelte';
	import SignalSummary from '#lib/components/document/SignalSummary.svelte';
	import StepDetails, { type DetailContext } from '#lib/components/document/StepDetails.svelte';
	import TokenInfo from '#lib/components/document/TokenInfo.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { formatDuration } from '#lib/duration.ts';
	import { formatTime } from '#lib/i18n.ts';
	import type { Lookup } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { labelled, reasonsText } from '#lib/reasons.ts';
	import { object, person } from '#lib/signals.ts';
	import { drawsDetails, drawsFacts } from '#lib/step-details.ts';
	import { YELLOW_ACTION } from '#lib/step-look.ts';
	import { actorOf, confirmationOf } from '#lib/step-summary.ts';
	import type { Step } from '#lib/steps.ts';
	import { usageOf } from '#lib/usage.ts';
	import { cn } from '#lib/utils.ts';
	import { viaToken } from '#lib/via-token.ts';

	type LogEntry = components['schemas']['LogEntry'];
	type Outcome = components['schemas']['Outcome'];

	// What a step did in the run shown, as the log told it before: per entry when, in which run,
	// with which model, the tokens and the prompt, how it ended and how long it took, why, and
	// what it said (drawn where a picture tells it better, `StepDetails`); for a step a person or
	// the rules overruled, how that came; for the verdict whose space waits, the way to the
	// filing question. Only editors read it.
	let {
		step,
		manageable,
		loading,
		current,
		lookup = null,
		filingHref = null,
		context,
		hasPrompt,
		onprompt
	}: {
		step: Step;
		manageable: boolean;
		loading: boolean;
		/** The run shown is the document's current one. */
		current: boolean;
		lookup?: Lookup | null;
		/** The filing question in the document tab, while the verdict's space waits. */
		filingHref?: string | null;
		/** What the drawn details need beyond the entry. */
		context: DetailContext;
		hasPrompt: (entry: LogEntry) => boolean;
		onprompt: (entry: LogEntry) => void;
	} = $props();

	const outcomeLabel: Record<Outcome, () => string> = {
		ok: m.outcome_ok,
		uncertain: m.outcome_uncertain,
		failed: m.outcome_failed
	};

	const time = formatTime;

	function overruled(entry: LogEntry, last: boolean): string | null {
		const confirmed = confirmationOf(entry);
		if (confirmed) {
			const name = viaToken(person(confirmed.by, lookup), confirmed.via);
			return confirmed.before === 'failed'
				? m.processing_overruled_decided({ name })
				: m.processing_overruled_confirmed({ name });
		}
		return last && step.overruled === 'settled' ? m.processing_overruled_settled() : null;
	}
</script>

<div class="@container flex flex-col gap-3">
	{#if !manageable}
		<p class="text-sm text-muted-foreground">{m.log_editors_only()}</p>
	{:else if step.done.entries.length === 0}
		{#if current}
			<p class="text-sm text-muted-foreground">{loading ? m.loading() : m.log_none()}</p>
		{/if}
	{:else}
		{#each step.done.entries as entry, index (`${entry.run}-${index}`)}
			{@const usage = usageOf(entry.output)}
			{@const settled = overruled(entry, index === step.done.entries.length - 1)}
			{@const actor = actorOf(entry)}
			<div class="flex flex-col gap-1.5 text-sm" data-run={entry.run}>
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
					<span>
						{time(entry.started_at)} · {m.log_run({
							run: entry.run
						})}{#if entry.model_version}{` · ${entry.model_version}`}{/if}{#if actor}{` · ${m.log_by(
								{ name: viaToken(person(actor.by, lookup), actor.via) }
							)}`}{/if}
					</span>
					{#if usage}
						<TokenInfo
							{usage}
							model={entry.model_version}
							id="tokens-{entry.node}-{entry.run}-{index}"
							pages={entry.node === 'ocr'}
						/>
					{/if}
					{#if hasPrompt(entry)}
						<Button
							variant="outline"
							size="sm"
							class="ml-auto"
							aria-haspopup="dialog"
							onclick={() => onprompt(entry)}
						>
							<MessageSquareCode aria-hidden="true" />
							{m.prompt_open()}
						</Button>
					{/if}
				</div>
				<!-- Side by side where there is room; a label above its value where not. -->
				<dl class="grid grid-cols-1 gap-x-3 gap-y-0.5 @sm:grid-cols-[auto_minmax(0,1fr)]">
					<dt class="text-muted-foreground">{m.log_outcome()}</dt>
					<dd class="whitespace-nowrap">
						{outcomeLabel[entry.outcome]()} · {formatDuration(entry.duration_ms / 1000)}
					</dd>
					{#if settled}
						<dt class="text-muted-foreground">{m.run_overruled()}</dt>
						<dd>{settled}</dd>
					{/if}
					{#if entry.reason}
						<dt class="text-muted-foreground">{m.log_reason()}</dt>
						<dd class="wrap-break-word">
							{reasonsText(entry.reasons, entry.reason, labelled(lookup))}
						</dd>
					{/if}
					{#if drawsFacts(entry)}
						<FactRows output={object(entry.output)} {lookup} />
					{:else if !drawsDetails(entry)}
						<SignalSummary {entry} {lookup} />
					{/if}
				</dl>
				{#if drawsDetails(entry)}<StepDetails {entry} {lookup} {context} />{/if}
			</div>
		{/each}
		{#if filingHref && step.node === 'judge'}
			<Button href={filingHref} size="sm" class={cn('self-start', YELLOW_ACTION)}>
				{m.processing_filing_link()}
			</Button>
		{/if}
	{/if}
</div>
