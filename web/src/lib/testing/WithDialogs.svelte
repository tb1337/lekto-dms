<script lang="ts">
	import type { Component } from 'svelte';
	import MasterDataDialogHost from '#lib/components/MasterDataDialogHost.svelte';

	// For tests: a component with the master data dialogs the app's layout hosts.
	let { component: Inner = null }: { component?: Component | null } = $props();
</script>

{#if Inner}<Inner />{/if}
<MasterDataDialogHost />
