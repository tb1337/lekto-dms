<script lang="ts">
	import CalendarIcon from '@lucide/svelte/icons/calendar';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { parseDate, type DateValue } from '@internationalized/date';
	import { DatePicker } from 'bits-ui';
	import { FIELD, FIELD_HEIGHT } from '#lib/components/ui/field-look.ts';
	import { getLocale, regionalLocale } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { cn } from '#lib/utils.ts';

	// A date in the language of the UI (web/DESIGN.md, "Fields"), not of the browser as the
	// native date input has it: day, month and year to type, and a calendar beside them. The
	// value is a day as the API writes it (`2026-10-26`), or '' for none.
	let {
		value = $bindable(''),
		id,
		label,
		min,
		max,
		disabled = false,
		invalid = false,
		class: className,
		onchange
	}: {
		value?: string;
		id?: string;
		/** The field's name for screen readers (the visible label stands beside it). */
		label: string;
		min?: string;
		max?: string;
		disabled?: boolean;
		invalid?: boolean;
		class?: string;
		onchange?: (value: string) => void;
	} = $props();

	function toDate(text: string | undefined): DateValue | undefined {
		if (!text) return undefined;
		try {
			return parseDate(text.slice(0, 10));
		} catch {
			return undefined;
		}
	}

	const locale = regionalLocale(getLocale());
</script>

<DatePicker.Root
	bind:value={
		() => toDate(value),
		(next) => {
			value = next ? next.toString() : '';
			onchange?.(value);
		}
	}
	{locale}
	minValue={toDate(min)}
	maxValue={toDate(max)}
	{disabled}
	weekdayFormat="short"
	fixedWeeks
>
	<DatePicker.Input
		{id}
		aria-label={label}
		aria-invalid={invalid || undefined}
		class={cn(
			FIELD,
			FIELD_HEIGHT,
			'flex items-center gap-0.5 pr-1.5 focus-within:border-ring',
			disabled && 'cursor-not-allowed opacity-50',
			className
		)}
	>
		{#snippet children({ segments })}
			{#each segments as { part, value: text }, index (index)}
				<DatePicker.Segment
					{part}
					class={cn(
						'rounded-xs px-0.5 tabular-nums outline-none focus:bg-primary/15 focus:text-foreground aria-[valuetext=Empty]:text-muted-foreground',
						part === 'literal' && 'px-0 text-muted-foreground'
					)}
				>
					{text}
				</DatePicker.Segment>
			{/each}
			<DatePicker.Trigger
				class="relative ml-auto grid size-8 place-items-center rounded-lg text-muted-foreground after:absolute after:-inset-1.5 hover:bg-secondary hover:text-foreground"
				aria-label={m.date_pick()}
			>
				<CalendarIcon class="size-4" aria-hidden="true" />
			</DatePicker.Trigger>
		{/snippet}
	</DatePicker.Input>
	<DatePicker.Portal>
		<DatePicker.Content
			sideOffset={6}
			collisionPadding={8}
			class="z-50 rounded-2xl border bg-popover p-3 text-popover-foreground shadow-lg"
		>
			<DatePicker.Calendar>
				{#snippet children({ months, weekdays })}
					<DatePicker.Header class="flex items-center justify-between gap-2 pb-2">
						<DatePicker.PrevButton
							class="grid size-8 place-items-center rounded-lg hover:bg-secondary"
							aria-label={m.date_previous_month()}
						>
							<ChevronLeft class="size-4" aria-hidden="true" />
						</DatePicker.PrevButton>
						<DatePicker.Heading class="text-sm font-medium" />
						<DatePicker.NextButton
							class="grid size-8 place-items-center rounded-lg hover:bg-secondary"
							aria-label={m.date_next_month()}
						>
							<ChevronRight class="size-4" aria-hidden="true" />
						</DatePicker.NextButton>
					</DatePicker.Header>
					{#each months as month (month.value.toString())}
						<DatePicker.Grid class="border-collapse">
							<DatePicker.GridHead>
								<DatePicker.GridRow class="flex">
									{#each weekdays as day, index (index)}
										<DatePicker.HeadCell class="w-9 text-xs font-normal text-muted-foreground">
											{day}
										</DatePicker.HeadCell>
									{/each}
								</DatePicker.GridRow>
							</DatePicker.GridHead>
							<DatePicker.GridBody>
								{#each month.weeks as week, index (index)}
									<DatePicker.GridRow class="flex">
										{#each week as date (date.toString())}
											<DatePicker.Cell {date} month={month.value} class="p-0">
												<DatePicker.Day
													class="grid size-9 place-items-center rounded-lg text-sm tabular-nums hover:bg-secondary data-disabled:pointer-events-none data-disabled:opacity-40 data-outside-month:text-muted-foreground/60 data-selected:bg-primary data-selected:font-medium data-selected:text-primary-foreground data-today:ring-1 data-today:ring-primary/40"
												/>
											</DatePicker.Cell>
										{/each}
									</DatePicker.GridRow>
								{/each}
							</DatePicker.GridBody>
						</DatePicker.Grid>
					{/each}
				{/snippet}
			</DatePicker.Calendar>
		</DatePicker.Content>
	</DatePicker.Portal>
</DatePicker.Root>
