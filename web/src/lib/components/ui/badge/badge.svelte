<script lang="ts" module>
	import { type VariantProps, tv } from 'tailwind-variants';

	import { TONE_EDGE, TONE_FILL, type Tone } from '#lib/tones.ts';

	// A state or a short fact (web/DESIGN.md, "Badges"): a pill in a tone, never a button. `default`
	// is the accent; `outline` names a person or an owner.
	const tones = Object.fromEntries(
		(Object.keys(TONE_FILL) as Tone[]).map((tone) => [
			tone,
			`${TONE_FILL[tone]} ${TONE_EDGE[tone]}`
		])
	) as Record<Tone, string>;

	export const badgeVariants = tv({
		base: 'gap-1 rounded-full border border-transparent font-medium transition-all has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 group/badge inline-flex w-fit shrink-0 items-center justify-center overflow-hidden whitespace-nowrap focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring [&>svg]:pointer-events-none',
		variants: {
			variant: {
				default: 'bg-primary text-primary-foreground [a]:hover:bg-primary/80',
				outline: 'border-border text-foreground [a]:hover:bg-muted',
				...tones
			},
			size: {
				sm: 'h-5 px-2 text-xs [&>svg]:size-3!',
				md: 'h-6 px-2.5 text-xs [&>svg]:size-3.5!',
				/** The lane of a document in its row or head. */
				lg: 'h-7 gap-1.5 pr-3 pl-2.5 text-meta font-semibold [&>svg]:size-[15px]!'
			}
		},
		defaultVariants: {
			variant: 'default',
			size: 'sm'
		}
	});

	export type BadgeVariant = VariantProps<typeof badgeVariants>['variant'];
</script>

<script lang="ts">
	import { cn, type WithElementRef } from '#lib/utils.ts';
	import type { HTMLAnchorAttributes } from 'svelte/elements';

	let {
		ref = $bindable(null),
		href,
		class: className,
		variant = 'default',
		size = 'sm',
		children,
		...restProps
	}: WithElementRef<HTMLAnchorAttributes> & {
		variant?: BadgeVariant;
		size?: 'sm' | 'md' | 'lg';
	} = $props();
</script>

<svelte:element
	this={href ? 'a' : 'span'}
	bind:this={ref}
	data-slot="badge"
	{href}
	class={cn(badgeVariants({ variant, size }), className)}
	{...restProps}
>
	{@render children?.()}
</svelte:element>
