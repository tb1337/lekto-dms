<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import { toast } from 'svelte-sonner';
	import type { components } from '#lib/api/schema.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { splitInput } from '#lib/usage.ts';
	import { cn } from '#lib/utils.ts';

	type Call = components['schemas']['ModelCallOut'];

	// What a node sent to the language model and what came back: system and user message and
	// the answer, each with its length and tokens (the input tokens split by characters).
	let {
		open = $bindable(false),
		title,
		meta,
		calls
	}: { open?: boolean; title: string; meta: string; calls: readonly Call[] } = $props();

	type Part = 'system' | 'user' | 'answer';
	let part = $state<Part>('system');
	let attempt = $state(0);

	const call = $derived(calls[Math.min(attempt, calls.length - 1)] ?? null);
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

	async function copy() {
		try {
			await navigator.clipboard.writeText(body);
			toast.success(m.content_copied());
		} catch (error) {
			toast.error(describeError(error));
		}
	}

	const parts: { part: Part; label: () => string }[] = [
		{ part: 'system', label: m.prompt_system },
		{ part: 'user', label: m.prompt_user },
		{ part: 'answer', label: m.prompt_answer }
	];
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="max-w-3xl">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{meta}</Dialog.Description>
		</Dialog.Header>
		<div class="flex flex-wrap items-center gap-3">
			<div
				role="group"
				aria-label={m.prompt_part()}
				class="flex gap-0.5 rounded-xl border bg-card p-[3px]"
			>
				{#each parts as entry (entry.part)}
					<button
						type="button"
						aria-pressed={part === entry.part}
						onclick={() => (part = entry.part)}
						class={cn(
							'h-8 rounded-[10px] px-3 text-sm transition-colors',
							part === entry.part
								? 'bg-primary font-medium text-primary-foreground'
								: 'text-muted-foreground hover:text-foreground'
						)}
					>
						{entry.label()}
					</button>
				{/each}
			</div>
			{#if calls.length > 1}
				<div role="group" aria-label={m.prompt_attempt_choice()} class="flex gap-1">
					{#each calls.keys() as index (index)}
						<button
							type="button"
							aria-pressed={attempt === index}
							onclick={() => (attempt = index)}
							class={cn(
								'h-8 rounded-full border px-3 text-sm',
								attempt === index
									? 'border-primary bg-secondary font-medium'
									: 'text-muted-foreground'
							)}
						>
							{m.prompt_attempt({ number: index + 1, total: calls.length })}
						</button>
					{/each}
				</div>
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
