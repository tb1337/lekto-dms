<script lang="ts">
	import { page } from '$app/state';
	import Logo from '#lib/components/Logo.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { home } from '#lib/navigation.ts';
	import { m } from '#lib/paraglide/messages.js';
	import PageTitle from '#lib/components/page/PageTitle.svelte';

	const notFound = $derived(page.status === 404);
</script>

<svelte:head><title>{notFound ? m.error_not_found() : m.error_title()}</title></svelte:head>

<main class="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6">
	<Logo class="text-xl" />
	<PageTitle>
		{notFound ? m.error_not_found() : m.error_title()}
	</PageTitle>
	{#if !notFound && page.error?.message}
		<p class="text-muted-foreground">{page.error.message}</p>
	{/if}
	<div class="flex gap-3">
		<Button href={home()}>{m.error_home()}</Button>
		{#if !notFound}
			<Button variant="secondary" onclick={() => location.reload()}>{m.error_retry()}</Button>
		{/if}
	</div>
</main>
