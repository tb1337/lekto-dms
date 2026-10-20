<script lang="ts" module>
	export interface Option {
		value: string;
		label: string;
	}
</script>

<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { Select as SelectPrimitive } from 'bits-ui';
	import { phone } from '#lib/phone.svelte.ts';
	import { cn } from '#lib/utils.ts';

	// A choice from a short, fixed list, styled like the inputs. On a phone the system's own
	// picker (the most comfortable with a thumb, Tobi 20.10.2026); wider, a list in the look of
	// the other pickers, by keyboard too (arrows, typing the first letters, Enter).
	let {
		value = $bindable(''),
		options,
		id,
		class: className = '',
		disabled = false,
		'aria-label': ariaLabel,
		'aria-invalid': ariaInvalid,
		onchange
	}: {
		value?: string;
		options: readonly Option[];
		id?: string;
		class?: string;
		disabled?: boolean;
		'aria-label'?: string;
		'aria-invalid'?: boolean;
		/** Called with the new value when the user picks one. */
		onchange?: (value: string) => void;
	} = $props();

	const FIELD =
		'h-11 w-full min-w-0 rounded-xl border border-input bg-card px-3 text-base transition-colors focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive md:text-sm dark:bg-input/30';
	const shown = $derived(options.find((option) => option.value === value)?.label ?? '');
</script>

{#if phone.current}
	<select
		{id}
		bind:value
		{disabled}
		aria-label={ariaLabel}
		aria-invalid={ariaInvalid}
		onchange={(event) => onchange?.(event.currentTarget.value)}
		class={cn(FIELD, className)}
	>
		{#each options as option (option.value)}
			<option value={option.value}>{option.label}</option>
		{/each}
	</select>
{:else}
	<SelectPrimitive.Root
		type="single"
		{value}
		{disabled}
		items={[...options]}
		onValueChange={(next) => {
			value = next;
			onchange?.(next);
		}}
	>
		<!-- A combobox as the native select is one: named by its label, its value read out. -->
		<SelectPrimitive.Trigger
			{id}
			role="combobox"
			data-value={value}
			aria-label={ariaLabel}
			aria-invalid={ariaInvalid}
			class={cn(FIELD, 'flex items-center gap-2 text-left', className)}
		>
			<span class="min-w-0 flex-1 truncate">{shown}</span>
			<ChevronDown class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
		</SelectPrimitive.Trigger>
		<SelectPrimitive.Portal>
			<SelectPrimitive.Content
				sideOffset={4}
				class="z-50 max-h-(--bits-select-content-available-height) min-w-(--bits-select-anchor-width) overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0"
			>
				<SelectPrimitive.Viewport>
					{#each options as option (option.value)}
						<SelectPrimitive.Item
							value={option.value}
							label={option.label}
							class="relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
						>
							{#snippet children({ selected })}
								<span class="min-w-0 flex-1 truncate">{option.label}</span>
								{#if selected}
									<Check class="absolute right-2 size-4" aria-hidden="true" />
								{/if}
							{/snippet}
						</SelectPrimitive.Item>
					{/each}
				</SelectPrimitive.Viewport>
			</SelectPrimitive.Content>
		</SelectPrimitive.Portal>
	</SelectPrimitive.Root>
{/if}
