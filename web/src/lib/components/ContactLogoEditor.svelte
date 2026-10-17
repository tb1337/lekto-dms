<script lang="ts">
	import Globe from '@lucide/svelte/icons/globe';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Upload from '@lucide/svelte/icons/upload';
	import { toast } from 'svelte-sonner';
	import ContactAvatar from '#lib/components/ContactAvatar.svelte';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { describeError } from '#lib/errors.ts';
	import { formatDate } from '#lib/i18n.ts';
	import { domainsOf, fetchLogo, removeLogo, uploadLogo } from '#lib/logos.ts';
	import type { Contact } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';

	// A contact's logo in its dialog: what it shows (the logo or its initials) and where the logo
	// came from; upload (PNG, JPEG or WebP), remove, and, where the server fetches logos and the
	// contact has a domain, fetch it from the website (never in place of an uploaded one). Each
	// action is saved at once, apart from the dialog's own fields.
	let {
		contact,
		fetching,
		onchanged
	}: {
		contact: Pick<Contact, 'id' | 'name' | 'logo' | 'logo_failure' | 'identifiers'>;
		/** The server fetches logos. */
		fetching: boolean;
		onchanged: () => void;
	} = $props();

	let logo = $state<Contact['logo']>(null);
	let failure = $state<Contact['logo_failure']>(null);
	let busy = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	$effect(() => {
		logo = contact.logo;
		failure = contact.logo_failure;
	});

	const canFetch = $derived(
		fetching && logo?.source !== 'uploaded' && domainsOf(contact).length > 0
	);

	async function run(action: () => Promise<void>) {
		if (busy) return;
		busy = true;
		try {
			await action();
		} catch (problem) {
			toast.error(describeError(problem));
		} finally {
			busy = false;
		}
	}

	function chosen(event: Event & { currentTarget: HTMLInputElement }) {
		const file = event.currentTarget.files?.[0];
		event.currentTarget.value = '';
		if (!file) return;
		void run(async () => {
			const saved = await uploadLogo(contact.id, file);
			logo = saved.logo;
			failure = saved.logo_failure;
			toast.success(m.logo_saved());
			onchanged();
		});
	}
</script>

<div class="flex flex-col gap-2">
	<div class="flex items-center gap-3">
		<ContactAvatar contact={{ name: contact.name, logo }} size="lg" />
		<div class="flex min-w-0 flex-col text-sm">
			{#if logo?.source === 'uploaded'}
				<span>{m.logo_uploaded({ date: formatDate(logo.stored_at) })}</span>
			{:else if logo?.source === 'fetched'}
				<span class="break-words">
					{m.logo_fetched({ domain: logo.domain ?? '', date: formatDate(logo.stored_at) })}
				</span>
			{:else}
				<span class="text-muted-foreground">{m.logo_none()}</span>
			{/if}
			{#if failure}
				<span class="text-xs break-words text-muted-foreground">
					{m.logo_failed({
						domains: failure.domains.join(', '),
						date: formatDate(failure.failed_at)
					})}
				</span>
			{/if}
		</div>
	</div>
	<div class="flex flex-wrap gap-2">
		<input
			bind:this={input}
			type="file"
			accept="image/png,image/jpeg,image/webp"
			class="hidden"
			onchange={chosen}
			tabindex="-1"
			aria-hidden="true"
		/>
		<Button variant="outline" size="sm" disabled={busy} onclick={() => input?.click()}>
			<Upload aria-hidden="true" />
			{m.logo_upload()}
		</Button>
		{#if logo}
			<Button
				variant="ghost"
				size="sm"
				disabled={busy}
				onclick={() =>
					run(async () => {
						await removeLogo(contact.id);
						logo = null;
						failure = null;
						toast.success(m.logo_removed());
						onchanged();
					})}
			>
				<Trash2 aria-hidden="true" />
				{m.logo_remove()}
			</Button>
		{/if}
		{#if canFetch}
			<Button
				variant="ghost"
				size="sm"
				disabled={busy}
				onclick={() =>
					run(async () => {
						await fetchLogo(contact.id);
						toast.info(m.logo_fetch_queued());
					})}
			>
				<Globe aria-hidden="true" />
				{m.logo_fetch()}
			</Button>
		{/if}
	</div>
	<p class="text-xs text-muted-foreground">
		{m.logo_upload_hint()}
		{#if canFetch}{m.logo_fetch_hint()}{/if}
	</p>
</div>
