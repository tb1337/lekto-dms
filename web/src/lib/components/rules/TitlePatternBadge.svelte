<script lang="ts">
	import { BASE } from '#lib/base.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.ts';

	// The rule of a document type's title pattern: a badge, for admins a link to the type.
	let { documentTypeId, name }: { documentTypeId: string; name: string } = $props();
</script>

<Badge variant="secondary">
	{#if session.isAdmin}
		<a
			href="{BASE}/admin/master-data?tab=document-types&type={documentTypeId}"
			class="hover:underline">{m.rule_title_pattern_of({ type: name })}</a
		>
	{:else}
		{m.rule_title_pattern_of({ type: name })}
	{/if}
</Badge>
