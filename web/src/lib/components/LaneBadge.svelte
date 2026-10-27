<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import Clock from '@lucide/svelte/icons/clock';
	import OctagonX from '@lucide/svelte/icons/octagon-x';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { laneTone, type Lane } from '#lib/tones.ts';

	// A document's lane as a badge in its tone, with icon and word. A document without a lane is
	// still being processed.
	let {
		lane,
		size = 'lg',
		class: className = ''
	}: { lane: Lane | null; size?: 'md' | 'lg'; class?: string } = $props();

	const looks = {
		green: { icon: CircleCheck, label: m.lane_green },
		yellow: { icon: TriangleAlert, label: m.lane_yellow },
		red: { icon: OctagonX, label: m.lane_red },
		running: { icon: Clock, label: m.lane_running }
	};

	const look = $derived(looks[lane ?? 'running']);
</script>

<Badge data-lane={lane ?? 'running'} variant={laneTone(lane)} {size} class={className}>
	<look.icon aria-hidden="true" strokeWidth={2.2} />
	{look.label()}
</Badge>
