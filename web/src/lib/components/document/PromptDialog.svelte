<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import type { components } from '#lib/api/schema.ts';
	import { copyText } from '#lib/clipboard.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import Segmented from '#lib/components/Segmented.svelte';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { splitInput } from '#lib/usage.ts';

	const PARTS: { part: 'system' | 'user' | 'answer'; label: () => string }[] = [
		{ part: 'system', label: m.prompt_system },
		{ part: 'user', label: m.prompt_user },
		{ part: 'answer', label: m.prompt_answer }
	];

	type Call = components['schemas']['ModelCallOut'];

	// What a node sent to the language model and what came back: system and user message and
	// the answer, each with its length and tokens (the input tokens split by characters). A
	// webhook that answered for the model got no system message: the context and its answer.
	let {
		open = $bindable(false),
		title,
		meta,
		calls
	}: { open?: boolean; title: string; meta: string; calls: readonly Call[] } = $props();

	type Part = 'system' | 'user' | 'answer';
	let chosenPart = $state<Part>('system');
	// The attempt chosen, among the calls it was chosen from: another prompt in the same dialog
	// starts at the first again.
	let chosen = $state.raw<{ among: readonly Call[]; index: number } | null>(null);
	const attempt = $derived(chosen?.among === calls ? chosen.index : 0);

	const call = $derived(calls[Math.min(attempt, calls.length - 1)] ?? null);
	const shown = $derived(
		call?.system === '' ? PARTS.filter((entry) => entry.part !== 'system') : PARTS
	);
	const part = $derived(
		shown.some((entry) => entry.part === chosenPart) ? chosenPart : shown[0].part
	);
	const body = $derived(call ? call[part] : '');
	const counted = (value: unknown) => (typeof value === 'number' ? value : null);
	const size = $derived.by(() => {
		if (!call) return '';
		const characters = formatNumber(body.length);
		const input = counted(call.usage.prompt_tokens);
		const output = counted(call.usage.completion_tokens);
		if (part === 'answer') {
			return output === null
				? m.prompt_characters({ characters })
				: m.prompt_output({ characters, tokens: formatNumber(output) });
		}
		if (input === null) return m.prompt_characters({ characters });
		const [system, user] = splitInput(input, call.system, call.user);
		return m.prompt_input({ characters, tokens: formatNumber(part === 'system' ? system : user) });
	});

	const copy = () => copyText(body);
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-3xl">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{meta}</Dialog.Description>
		</Dialog.Header>
		<div class="flex flex-wrap items-center gap-3">
			<Segmented
				label={m.prompt_part()}
				value={part}
				options={shown.map((entry) => ({ value: entry.part, label: entry.label() }))}
				onchange={(next) => (chosenPart = next as Part)}
			/>
			{#if calls.length > 1}
				<Segmented
					label={m.prompt_attempt_choice()}
					value={String(attempt)}
					options={[...calls.keys()].map((index) => ({
						value: String(index),
						label: m.prompt_attempt({ number: index + 1, total: calls.length })
					}))}
					onchange={(next) => (chosen = { among: calls, index: Number(next) })}
				/>
			{/if}
			<span class="text-sm text-muted-foreground">{size}</span>
		</div>
		<pre
			class="h-[min(28rem,55vh)] overflow-auto rounded-xl border bg-surface px-4 py-3.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap">{body}</pre>
		<Dialog.Footer class="items-center sm:justify-between">
			<p class="text-sm text-muted-foreground">{m.prompt_document_note()}</p>
			<div class="flex gap-2">
				<Button variant="outline" onclick={copy}>
					<Copy aria-hidden="true" />
					{m.content_copy()}
				</Button>
				<Button onclick={() => (open = false)}>{m.close()}</Button>
			</div>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
