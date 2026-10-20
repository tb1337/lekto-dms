<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import * as Popover from '#lib/components/ui/popover/index.ts';
	import { m } from '#lib/paraglide/messages.js';

	// The help of a field behind a small info button beside its label, not under the field
	// (Tobi, 20.10.2026): a click or tap opens it, Escape or a click elsewhere closes it. With
	// `id` the text is also there hidden, for the field's `aria-describedby`.
	let { text, about, id }: { text: string; about: string; id?: string } = $props();
</script>

<Popover.Root>
	<Popover.Trigger
		aria-label={m.hint_about({ name: about })}
		class="grid size-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground data-[state=open]:bg-secondary data-[state=open]:text-foreground"
	>
		<Info class="size-3.5" aria-hidden="true" />
	</Popover.Trigger>
	<Popover.Content align="start" collisionPadding={8} class="w-80 text-sm leading-relaxed">
		{text}
	</Popover.Content>
</Popover.Root>
{#if id}<span {id} hidden>{text}</span>{/if}
