<script lang="ts">
	import { beforeNavigate, goto } from '$app/navigation';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import { m } from '#lib/paraglide/messages.js';

	// Asks before changes are lost (web/DESIGN.md, "Saving and leaving"): while `dirty`, leaving
	// the page by a link, a tab, the back button or closing the window asks first; "Discard"
	// goes on, anything else stays. The form clears `dirty` once it saved or the person cancelled.
	// `keeps`: a move within the page that keeps the form (a pane shown instead of another) asks
	// nothing.
	let { dirty, keeps }: { dirty: boolean; keeps?: (from: URL, to: URL) => boolean } = $props();

	let asking = $state(false);
	let target = $state<URL | null>(null);
	let leaving = false;

	beforeNavigate((navigation) => {
		if (!dirty || leaving) return;
		// Closing the window or leaving the app: only the browser's own question is possible.
		if (navigation.type === 'leave') {
			navigation.cancel();
			return;
		}
		if (!navigation.to) return;
		if (navigation.from && keeps?.(navigation.from.url, navigation.to.url)) return;
		navigation.cancel();
		target = navigation.to.url;
		asking = true;
	});

	async function discard() {
		if (!target) return;
		leaving = true;
		asking = false;
		await goto(target);
		leaving = false;
	}
</script>

<ConfirmDialog
	bind:open={asking}
	title={m.unsaved_title()}
	description={m.unsaved_hint()}
	confirmLabel={m.unsaved_discard()}
	onconfirm={discard}
/>
