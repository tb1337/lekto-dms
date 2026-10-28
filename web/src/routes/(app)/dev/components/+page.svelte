<script lang="ts">
	import InboxIcon from '@lucide/svelte/icons/inbox';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import List from '@lucide/svelte/icons/list';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Plus from '@lucide/svelte/icons/plus';
	import Tag from '@lucide/svelte/icons/tag';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import { toast } from 'svelte-sonner';
	import Chip from '#lib/components/Chip.svelte';
	import DateInput from '#lib/components/DateInput.svelte';
	import EmptyNote from '#lib/components/EmptyNote.svelte';
	import FoldedGroup from '#lib/components/FoldedGroup.svelte';
	import FormDialog from '#lib/components/FormDialog.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import InfoTip from '#lib/components/InfoTip.svelte';
	import LaneBadge from '#lib/components/LaneBadge.svelte';
	import Loading from '#lib/components/Loading.svelte';
	import Figure from '#lib/components/overview/Figure.svelte';
	import Tile from '#lib/components/overview/Tile.svelte';
	import SearchSelect from '#lib/components/SearchSelect.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import Select from '#lib/components/Select.svelte';
	import SelectionBar from '#lib/components/SelectionBar.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import Eyebrow from '#lib/components/page/Eyebrow.svelte';
	import PageHeader from '#lib/components/page/PageHeader.svelte';
	import SectionTitle from '#lib/components/page/SectionTitle.svelte';
	import VolumeMeter from '#lib/components/VolumeMeter.svelte';
	import * as Alert from '#lib/components/ui/alert/index.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Card from '#lib/components/ui/card/index.ts';
	import { Choice } from '#lib/components/ui/choice/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import * as Field from '#lib/components/ui/field/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Skeleton } from '#lib/components/ui/skeleton/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';
	import { formatDate, formatMoney, formatNumber } from '#lib/i18n.ts';
	import { m } from '#lib/paraglide/messages.js';
	import type { Tone } from '#lib/tones.ts';

	// The living style guide of web/DESIGN.md: every component of the design system in its
	// variants and sizes, as the pages use them. Names of variants are shown as the code spells
	// them; sample data, not translated, stands for user content.
	const rows = [
		{ title: 'Stadtwerke · Abschlag', date: new Date(2026, 9, 1), lane: 'green' as const },
		{ title: 'Hausrat · Beitrag 2027', date: new Date(2026, 8, 28), lane: 'yellow' as const },
		{ title: 'Finanzamt · Bescheid', date: new Date(2026, 8, 19), lane: 'red' as const },
		{ title: 'scan_0042.pdf', date: new Date(2026, 9, 8), lane: null }
	];
	const BUTTONS = ['default', 'secondary', 'outline', 'ghost', 'destructive', 'link'] as const;
	const TONES: Tone[] = ['green', 'yellow', 'red', 'running', 'muted', 'note', 'primary'];
	const CHIPS = ['neutral', 'outline', 'selected', 'add'] as const;
	const CARDS = ['row', 'sm', 'md', 'lg'] as const;
	const DIALOGS = ['sm', 'md', 'lg', 'xl'] as const;
	const ALERTS = ['default', 'note', 'tip', 'warning', 'caution'] as const;
	/** The toggle chip, named by its prop. */
	const PRESSED = 'pressed';

	let pressed = $state(true);
	let checked = $state(true);
	let radio = $state('one');
	let on = $state(true);
	let picked = $state('one');
	let day = $state('2026-10-26');
	let view = $state('grid');
	let contact = $state('c1');
	let folded = $state(false);
	let formOpen = $state(false);
	const options = [
		{ value: 'one', label: `${m.dev_sample_option()} 1` },
		{ value: 'two', label: `${m.dev_sample_option()} 2` }
	];
	const CONTACTS = [
		{ value: 'c1', label: 'Stadtwerke Nord' },
		{ value: 'c2', label: 'Hausverwaltung Ost', keywords: 'HVO' }
	];
</script>

<svelte:head><title>{m.dev_components_title()} · {m.app_name()}</title></svelte:head>

<div class="flex flex-col gap-10">
	<PageHeader title={m.dev_components_title()} subtitle={m.dev_components_hint()} />

	<section class="flex flex-col gap-3" aria-labelledby="dev-type">
		<SectionTitle id="dev-type">{m.dev_section_type()}</SectionTitle>
		<Eyebrow>{m.dev_sample_eyebrow()}</Eyebrow>
		<SectionTitle level={3}>{m.dev_sample_heading()}</SectionTitle>
		<SectionTitle level={3} size="card">{m.dev_sample_heading()}</SectionTitle>
		<p class="max-w-prose">{m.dev_sample_text()}</p>
		<p class="text-sm text-muted-foreground">{m.dev_sample_text()}</p>
		<p class="text-meta text-muted-foreground">{m.dev_sample_text()}</p>
		<p class="text-xs text-muted-foreground">{m.dev_sample_text()}</p>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-buttons">
		<SectionTitle id="dev-buttons">{m.dev_section_buttons()}</SectionTitle>
		<div class="flex flex-wrap items-center gap-3">
			{#each BUTTONS as variant (variant)}
				<Button {variant}>{variant}</Button>
			{/each}
		</div>
		<div class="flex flex-wrap items-center gap-3">
			<Button size="lg">{m.dev_sample_button()}</Button>
			<Button>
				<Plus aria-hidden="true" />
				{m.dev_sample_button()}
			</Button>
			<Button size="sm" variant="outline">{m.dev_sample_button()}</Button>
			<IconButton label={m.dev_sample_button()}><Pencil aria-hidden="true" /></IconButton>
			<IconButton label={m.dev_sample_button()} variant="outline">
				<Pencil aria-hidden="true" />
			</IconButton>
			<IconButton label={m.dev_sample_destructive()} size="sm" variant="destructive">
				<Trash2 aria-hidden="true" />
			</IconButton>
		</div>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-badges">
		<SectionTitle id="dev-badges">{m.dev_section_badges()}</SectionTitle>
		{#each ['sm', 'md'] as const as size (size)}
			<div class="flex flex-wrap items-center gap-2">
				{#each TONES as tone (tone)}
					<Badge variant={tone} {size}>{tone}</Badge>
				{/each}
				{#each ['outline', 'default'] as const as variant (variant)}
					<Badge {variant} {size}>{variant}</Badge>
				{/each}
			</div>
		{/each}
		<div class="flex flex-wrap items-center gap-2">
			<LaneBadge lane="green" />
			<LaneBadge lane="yellow" />
			<LaneBadge lane="red" />
			<LaneBadge lane={null} />
		</div>
		<!-- A recommendation goes without an icon: its words tell. -->
		<div class="flex flex-wrap items-center gap-2">
			<Badge variant="green">{m.open_advise_confirm()}</Badge>
			<Badge variant="muted">{m.open_advise_reject()}</Badge>
		</div>
		<div class="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
			{#each [1, 2, 3] as const as level (level)}
				<span class="flex items-center gap-2">{level} <VolumeMeter {level} /></span>
			{/each}
		</div>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-chips">
		<SectionTitle id="dev-chips">{m.dev_section_chips()}</SectionTitle>
		{#each ['md', 'sm'] as const as size (size)}
			<div class="flex flex-wrap items-center gap-2">
				{#each CHIPS as variant (variant)}
					<Chip {variant} {size}>{variant}</Chip>
				{/each}
				<Chip {size} {pressed} onclick={() => (pressed = !pressed)}>{PRESSED}</Chip>
				<Chip
					{size}
					onremove={() => toast(m.dev_sample_remove())}
					removeLabel={m.dev_sample_remove()}
				>
					{#snippet icon()}<Tag class="size-3.5" aria-hidden="true" />{/snippet}
					{m.dev_sample_chip()}
				</Chip>
			</div>
		{/each}
	</section>

	<section class="flex max-w-sm flex-col gap-4" aria-labelledby="dev-fields">
		<SectionTitle id="dev-fields">{m.dev_section_fields()}</SectionTitle>
		<Field.Field>
			<span class="flex items-center gap-1.5">
				<Field.Label for="sample">{m.dev_sample_input()}</Field.Label>
				<InfoTip label={m.dev_sample_info()}>{m.dev_sample_info_text()}</InfoTip>
			</span>
			<Input id="sample" />
		</Field.Field>
		<Field.Field>
			<Field.Label for="sample-select">{m.dev_sample_option()}</Field.Label>
			<Select id="sample-select" {options} bind:value={picked} />
		</Field.Field>
		<Field.Field>
			<Field.Label for="sample-search">{m.dev_sample_search_select()}</Field.Label>
			<SearchSelect
				id="sample-search"
				title={m.dev_sample_search_select()}
				bind:value={contact}
				options={CONTACTS}
				placeholder={m.value_unset()}
				noneLabel={m.value_unset()}
			/>
		</Field.Field>
		<Field.Field>
			<Field.Label for="sample-date">{m.dev_sample_table_date()}</Field.Label>
			<DateInput id="sample-date" label={m.dev_sample_table_date()} bind:value={day} />
		</Field.Field>
		<Field.Field>
			<Field.Label for="sample-text">{m.dev_sample_input()}</Field.Label>
			<Textarea id="sample-text" />
		</Field.Field>
		<Choice bind:checked>{m.dev_sample_option()}</Choice>
		<div class="flex flex-col gap-2">
			<Choice type="radio" name="sample" value="one" bind:group={radio}>
				{m.dev_sample_option()} 1
			</Choice>
			<Choice type="radio" name="sample" value="two" bind:group={radio}>
				{m.dev_sample_option()} 2
			</Choice>
		</div>
		<span class="flex items-center gap-2 text-sm">
			<Switch bind:checked={on} aria-label={m.dev_sample_option()} />
			{m.dev_sample_option()}
		</span>
	</section>

	<section class="flex flex-col gap-4" aria-labelledby="dev-tabs">
		<SectionTitle id="dev-tabs">{m.dev_section_tabs()}</SectionTitle>
		<TabBar
			label={m.dev_section_tabs()}
			current="one"
			tabs={[
				{ key: 'one', href: '#dev-tabs', label: m.dev_sample_tab_one(), count: 12 },
				{
					key: 'two',
					href: '#dev-tabs',
					label: m.dev_sample_tab_two(),
					marker: m.dev_sample_info()
				}
			]}
		/>
		<div class="flex flex-wrap items-center gap-3">
			<Segmented
				label={m.dev_section_tabs()}
				bind:value={view}
				options={[
					{ value: 'grid', label: m.dev_sample_tab_one(), icon: LayoutGrid },
					{ value: 'list', label: m.dev_sample_tab_two(), icon: List }
				]}
			/>
			<Segmented
				label={m.dev_section_tabs()}
				size="sm"
				names="hidden"
				bind:value={view}
				options={[
					{ value: 'grid', label: m.dev_sample_tab_one(), icon: LayoutGrid },
					{ value: 'list', label: m.dev_sample_tab_two(), icon: List }
				]}
			/>
		</div>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-cards">
		<SectionTitle id="dev-cards">{m.dev_section_cards()}</SectionTitle>
		<div class="grid gap-3 sm:grid-cols-2">
			{#each CARDS as size (size)}
				<Card.Root {size} class="flex flex-col gap-1">
					<Card.Title level={3}>{size}</Card.Title>
					<p class="text-sm text-muted-foreground">{m.dev_sample_text()}</p>
				</Card.Root>
			{/each}
		</div>
		<Card.Root size="sm" class="flex max-w-xl flex-col gap-1">
			<p class="px-1 text-sm">{m.dev_sample_text()}</p>
			<FoldedGroup
				bind:open={folded}
				class="mt-1"
				count={m.dev_sample_folded_count()}
				hint={m.dev_sample_folded_hint()}
			>
				<p class="py-1 text-sm text-muted-foreground">{m.dev_sample_text()}</p>
				<p class="py-1 text-sm text-muted-foreground">{m.dev_sample_text()}</p>
			</FoldedGroup>
		</Card.Root>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-selection">
		<SectionTitle id="dev-selection">{m.dev_section_selection()}</SectionTitle>
		<SelectionBar count={m.selection_selected({ count: '3' })}>
			{#snippet hint()}{m.dev_sample_hint()}{/snippet}
			{#snippet trail()}
				<Button variant="ghost" size="sm">{m.dev_sample_secondary()}</Button>
			{/snippet}
			{#snippet actions()}
				<Button variant="outline" size="sm">{m.dev_sample_button()}</Button>
				<Button size="sm">{m.dev_sample_button()}</Button>
			{/snippet}
		</SelectionBar>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-tiles">
		<SectionTitle id="dev-tiles">{m.dev_section_tiles()}</SectionTitle>
		<div class="grid gap-4 sm:grid-cols-2">
			<Tile
				title={m.dev_sample_tile()}
				icon={InboxIcon}
				href="#dev-tiles"
				go={m.dev_sample_tile_go()}
			>
				<Figure count={12} label={m.overview_open()} />
				<p class="text-meta text-muted-foreground">{m.dev_sample_text()}</p>
			</Tile>
		</div>
	</section>

	<section class="flex flex-col gap-4" aria-labelledby="dev-states">
		<SectionTitle id="dev-states">{m.dev_section_states()}</SectionTitle>
		<Loading />
		<EmptyNote compact>
			{m.dev_sample_empty()}
			{#snippet action()}
				<Button variant="outline">
					<Plus aria-hidden="true" />
					{m.dev_sample_button()}
				</Button>
			{/snippet}
		</EmptyNote>
		<div class="flex max-w-xl flex-col gap-3">
			{#each ALERTS as variant (variant)}
				<Alert.Root {variant}>
					<Alert.Title>{variant}</Alert.Title>
					<Alert.Description>{m.error_network()}</Alert.Description>
				</Alert.Root>
			{/each}
			<div class="flex flex-col gap-2">
				<Skeleton class="h-4 w-3/4" />
				<Skeleton class="h-4 w-1/2" />
			</div>
		</div>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-dialogs">
		<SectionTitle id="dev-dialogs">{m.dev_section_dialogs()}</SectionTitle>
		<div class="flex flex-wrap gap-3">
			{#each DIALOGS as size (size)}
				<Dialog.Root>
					<Dialog.Trigger>
						{#snippet child({ props })}
							<Button variant="outline" {...props}>{m.dev_sample_open_dialog()} · {size}</Button>
						{/snippet}
					</Dialog.Trigger>
					<Dialog.Content {size}>
						<Dialog.Header>
							<Dialog.Title>{m.dev_sample_dialog_title()}</Dialog.Title>
							<Dialog.Description>{m.dev_sample_dialog_text()}</Dialog.Description>
						</Dialog.Header>
					</Dialog.Content>
				</Dialog.Root>
			{/each}
			<Button variant="outline" onclick={() => (formOpen = true)}>
				{m.dev_sample_open_form()}
			</Button>
			<Button variant="outline" onclick={() => toast.success(m.dev_sample_toast())}>
				{m.dev_sample_show_toast()}
			</Button>
		</div>
		<FormDialog
			bind:open={formOpen}
			title={m.dev_sample_dialog_title()}
			description={m.dev_sample_dialog_text()}
			submitLabel={m.dev_sample_button()}
			action={async () => {}}
			alternative={{ label: m.dev_sample_alternative(), action: async () => {} }}
		>
			<Field.Field>
				<Field.Label for="sample-form">{m.dev_sample_input()}</Field.Label>
				<Input id="sample-form" />
			</Field.Field>
		</FormDialog>
	</section>

	<section class="flex flex-col gap-3" aria-labelledby="dev-data">
		<SectionTitle id="dev-data">{m.dev_section_data()}</SectionTitle>
		<div class="flex flex-col gap-2 text-sm text-muted-foreground">
			<span>{formatDate(new Date())}</span>
			<span>{formatNumber(1234567.891)}</span>
			<span>{formatMoney('1234.50', 'EUR')}</span>
		</div>
		<Card.Root size="flush">
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>{m.dev_sample_table_title()}</Table.Head>
						<Table.Head>{m.dev_sample_table_date()}</Table.Head>
						<Table.Head>{m.dev_sample_table_lane()}</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each rows as row (row.title)}
						<Table.Row>
							<Table.Cell class="font-medium">{row.title}</Table.Cell>
							<Table.Cell class="text-muted-foreground tabular-nums">
								{formatDate(row.date)}
							</Table.Cell>
							<Table.Cell><LaneBadge lane={row.lane} /></Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
		</Card.Root>
	</section>
</div>
