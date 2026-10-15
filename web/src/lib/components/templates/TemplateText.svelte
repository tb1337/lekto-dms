<script lang="ts">
	import { segments } from '#lib/templates/liquid.ts';

	// A template as text, coloured like in the editor (where a rule is read).
	let { text, class: className = '' }: { text: string; class?: string } = $props();

	const parts = $derived(segments(text));
</script>

<span class="font-mono break-words whitespace-pre-wrap {className}"
	>{#each parts as part, index (index)}{#if part.kind}<span class="tpl-{part.kind}"
				>{part.text}</span
			>{:else}{part.text}{/if}{/each}</span
>
