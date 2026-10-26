<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// The icon of `static/favicon.svg` before the wordmark (Tobi, 26.10.2026), in the brand colour
	// (lighter in the dark theme) and sized by the writing, wherever the logo stands: the header,
	// the navigation sheet, the sign-in and the error page. Screen readers hear the name.
	let { class: className = '' }: { class?: string } = $props();
</script>

<span
	class={cn(
		'inline-flex items-center gap-[0.45em] font-mono font-medium tracking-tight',
		className
	)}
	aria-label={m.app_name()}
	role="img"
>
	<svg viewBox="0 0 32 32" class="size-[1.2em] shrink-0 text-brand" aria-hidden="true">
		<rect width="32" height="32" rx="8" fill="currentColor" />
		<path
			d="M7 9.5H12M7 15.5H10M7 21.5H12"
			fill="none"
			stroke="#fff"
			stroke-opacity="0.6"
			stroke-width="2.4"
			stroke-linecap="round"
		/>
		<circle cx="18.5" cy="15" r="5.5" fill="none" stroke="#fff" stroke-width="2.8" />
		<path d="M22.6 19.1L26 22.5" stroke="#fff" stroke-width="3" stroke-linecap="round" />
	</svg>
	lekto
</span>
