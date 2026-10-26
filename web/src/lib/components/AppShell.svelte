<script lang="ts">
	import type { Snippet } from 'svelte';
	import BookOpen from '@lucide/svelte/icons/book-open';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Languages from '@lucide/svelte/icons/languages';
	import LogOut from '@lucide/svelte/icons/log-out';
	import Menu from '@lucide/svelte/icons/menu';
	import Monitor from '@lucide/svelte/icons/monitor';
	import Moon from '@lucide/svelte/icons/moon';
	import SearchIcon from '@lucide/svelte/icons/search';
	import Sun from '@lucide/svelte/icons/sun';
	import SunMoon from '@lucide/svelte/icons/sun-moon';
	import Users from '@lucide/svelte/icons/users';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { API_DOCS, BASE } from '#lib/base.ts';
	import BetaPill from '#lib/components/BetaPill.svelte';
	import HeaderSearch from '#lib/components/HeaderSearch.svelte';
	import LanguageMenu from '#lib/components/LanguageMenu.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import Segmented from '#lib/components/Segmented.svelte';
	import ThemeMenu from '#lib/components/ThemeMenu.svelte';
	import { buttonVariants } from '#lib/components/ui/button/index.ts';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.ts';
	import * as Sheet from '#lib/components/ui/sheet/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';
	import { reportError } from '#lib/errors.ts';
	import { searchPlaces } from '#lib/header-search.ts';
	import { changeLanguage, getLocale, LANGUAGE_NAMES, locales, type Locale } from '#lib/i18n.ts';
	import { home, loginHref } from '#lib/navigation.ts';
	import { BADGE_TONES, badgeLabel, badgeText, badgeTone, inbox } from '#lib/inbox.svelte.ts';
	import { userLabel } from '#lib/masterdata.svelte.ts';
	import { m } from '#lib/paraglide/messages.js';
	import { canListAllUsers } from '#lib/permissions.ts';
	import { phone } from '#lib/phone.svelte.ts';
	import { scope } from '#lib/scope.svelte.ts';
	import { href, isCurrent, SETTINGS, visibleSections, type Section } from '#lib/sections.ts';
	import { session } from '#lib/session.svelte.ts';
	import { cn } from '#lib/utils.ts';
	import { onChange } from '#lib/watch.svelte.ts';

	let { children }: { children: Snippet } = $props();

	// The menu in two groups with a line between them (Tobi, 26.10.2026): the work, then setting
	// up and running Lekto; the admin areas stand last in the second.
	const sections = $derived(visibleSections(session.isAdmin));
	const workSections = $derived(sections.filter((section) => section.group === 'work'));
	const setupSections = $derived(sections.filter((section) => section.group === 'setup'));
	const username = $derived(session.user ? userLabel(session.user) : '');
	let menuOpen = $state(false);
	// A document opened from the inbox belongs to the inbox.
	const currentPath = $derived(
		page.url.searchParams.get('from') === 'inbox' ? `${home()}inbox` : page.url.pathname
	);

	async function signOut() {
		menuOpen = false;
		try {
			await session.logout();
		} catch (error) {
			reportError(error);
			return;
		}
		await goto(loginHref(home()), { replaceState: true });
	}

	const tone = $derived(badgeTone(inbox.summary));

	// The inbox counter covers what the scope setting covers.
	onChange(
		() => scope.allUsers,
		() => void inbox.refresh()
	);

	// Language and theme in the sheet on a phone, as pills in a row each.
	const languageOptions = locales.map((locale) => ({
		value: locale,
		label: LANGUAGE_NAMES[locale]
	}));
	const themeOptions = [
		{ value: 'light', label: m.theme_light(), icon: Sun },
		{ value: 'dark', label: m.theme_dark(), icon: Moon },
		{ value: 'system', label: m.theme_system(), icon: Monitor }
	];

	async function open(section: Section) {
		menuOpen = false;
		await goto(href(section));
	}
</script>

{#snippet pill(section: Section, vertical: boolean)}
	{@const current = isCurrent(section, currentPath)}
	<a
		href={href(section)}
		aria-current={current ? 'page' : undefined}
		onclick={() => (menuOpen = false)}
		class={cn(
			'flex h-9 items-center gap-2 rounded-full px-3 text-sm whitespace-nowrap transition-colors hover:text-foreground 2xl:px-3.5',
			current ? 'bg-secondary font-medium text-foreground' : 'text-muted-foreground',
			vertical && 'h-11 rounded-xl px-4 text-base'
		)}
	>
		{#if vertical}<section.icon class="size-[18px]" aria-hidden="true" />{/if}
		{section.label()}
		{#if section.path === '/inbox' && inbox.summary && tone}
			<!-- Coloured by the worst lane in it; the label says what stands there. -->
			<span
				role="img"
				data-tone={tone}
				class={cn(
					'grid h-5 min-w-5 place-items-center rounded-full border px-1.5 text-xs font-semibold',
					BADGE_TONES[tone]
				)}
				aria-label={badgeLabel(inbox.summary)}
			>
				{badgeText(inbox.open)}
			</span>
		{/if}
		{#if section.path === '/expected'}
			<!-- The area is new (Tobi, 26.10.2026). -->
			<BetaPill class="-ml-1" />
		{/if}
	</a>
{/snippet}

{#snippet allUsersMark()}
	<!-- An admin who sees all users is told so at a glance. -->
	<span
		class="absolute -top-0.5 -right-0.5 grid size-4 place-items-center rounded-full border-2 border-card bg-lane-yellow text-lane-yellow-foreground"
		aria-hidden="true"
	>
		<Users class="size-2.5" />
	</span>
{/snippet}

<a
	href="#main"
	class="sr-only z-50 rounded-xl bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
	>{m.skip_to_content()}</a
>

<!-- A page that needs the room (the document view) marks itself `data-wide`: from the desktop
	width on it fills the window, and only its own areas scroll. One that only needs the width
	(the documents) marks itself `data-roomy`: as wide, and it scrolls as a page. -->
<div class="flex min-h-screen flex-col lg:has-[[data-wide]]:h-dvh">
	<header class="sticky top-0 z-40 border-b bg-card">
		<!-- Narrower gaps on a phone, and a little narrower below 380 pixels, so that the wordmark,
		     the magnifier and the menu fit beside each other down to 360. -->
		<div class="flex h-16 items-center gap-2 px-4 max-[380px]:px-3 sm:gap-4 sm:px-8 lg:gap-7">
			<a href={home()} class="rounded-md text-lg"><Logo /></a>

			<!-- The menu in the header where it fits: from xl (German names are long). -->
			<nav aria-label={m.nav_main()} class="hidden min-w-0 flex-1 items-center gap-1 xl:flex">
				{#each workSections as section (section.path)}
					{@render pill(section, false)}
				{/each}
				<div class="mx-2 h-5 w-px bg-border" aria-hidden="true"></div>
				{#each setupSections as section (section.path)}
					{@render pill(section, false)}
				{/each}
			</nav>

			<div class="ml-auto flex items-center gap-1.5 max-[380px]:gap-1 sm:gap-2">
				<!-- The field where there is room, else a magnifier to the documents page's own
				     field (`header-search.ts`). -->
				<HeaderSearch class={searchPlaces(session.isAdmin).field} />
				<a
					href="{BASE}/documents#search"
					class={cn(
						buttonVariants({ variant: 'ghost', size: 'icon' }),
						searchPlaces(session.isAdmin).icon
					)}
					aria-label={m.header_search_label()}
				>
					<SearchIcon aria-hidden="true" />
				</a>
				<!-- On a phone the header holds only the magnifier and the menu: language, theme and
				     the account are in the sheet (Tobi, 26.10.2026). -->
				{#if !phone.current}
					<LanguageMenu />
					<ThemeMenu />
					<DropdownMenu.Root>
						<DropdownMenu.Trigger
							class={cn(
								buttonVariants({ size: 'icon' }),
								'relative font-semibold uppercase [&]:text-md'
							)}
							aria-label={scope.allUsers
								? m.account_menu_all_users({ username })
								: m.account_menu({ username })}
						>
							{username.slice(0, 1)}
							{#if scope.allUsers}{@render allUsersMark()}{/if}
						</DropdownMenu.Trigger>
						<DropdownMenu.Content align="end" class="w-64">
							<DropdownMenu.Label class="flex flex-col gap-0.5">
								<span class="font-semibold">{username}</span>
								<span class="text-xs font-normal text-muted-foreground">
									{session.isAdmin ? m.role_admin() : m.role_user()}
								</span>
							</DropdownMenu.Label>
							<DropdownMenu.Separator />
							{#if canListAllUsers(session.user)}
								<DropdownMenu.CheckboxItem
									checked={scope.allUsers}
									onCheckedChange={(checked) => scope.set(checked)}
									class="items-start"
								>
									<Users aria-hidden="true" class="mt-0.5" />
									<span class="flex flex-col gap-0.5">
										{m.all_users()}
										<span class="text-xs text-muted-foreground">{m.all_users_hint()}</span>
									</span>
								</DropdownMenu.CheckboxItem>
								<DropdownMenu.Separator />
							{/if}
							<DropdownMenu.Item onSelect={() => goto(href(SETTINGS))}>
								<SETTINGS.icon aria-hidden="true" />
								{SETTINGS.label()}
							</DropdownMenu.Item>
							<!-- The API's own documentation (Swagger UI), in a new tab. -->
							<DropdownMenu.Item>
								{#snippet child({ props })}
									<a {...props} href={API_DOCS} target="_blank" rel="noopener noreferrer">
										<BookOpen aria-hidden="true" />
										{m.api_docs()}
										<span class="sr-only">({m.opens_in_new_tab()})</span>
										<ExternalLink aria-hidden="true" class="ml-auto text-muted-foreground" />
									</a>
								{/snippet}
							</DropdownMenu.Item>
							<DropdownMenu.Item onSelect={signOut}>
								<LogOut aria-hidden="true" />
								{m.sign_out()}
							</DropdownMenu.Item>
						</DropdownMenu.Content>
					</DropdownMenu.Root>
				{/if}

				<!-- The menu below xl, at the outer right where the thumb is; the sheet opens from
				     the right. On a phone it holds the account too (Tobi, 26.10.2026, variant A). -->
				<Sheet.Root bind:open={menuOpen}>
					<Sheet.Trigger
						class={cn(buttonVariants({ variant: 'ghost', size: 'icon' }), 'relative xl:hidden')}
						aria-label={phone.current && scope.allUsers ? m.nav_open_all_users() : m.nav_open()}
					>
						<Menu aria-hidden="true" />
						{#if phone.current && scope.allUsers}{@render allUsersMark()}{/if}
					</Sheet.Trigger>
					<Sheet.Content side="right" class="w-80 gap-2 overflow-y-auto p-4">
						<Sheet.Header class="px-2">
							<Sheet.Title><Logo class="text-lg" /></Sheet.Title>
						</Sheet.Header>
						{#if phone.current}
							<div class="flex flex-col gap-0.5 px-4">
								<span class="text-base font-semibold">{username}</span>
								<span class="text-xs text-muted-foreground">
									{session.isAdmin ? m.role_admin() : m.role_user()}
								</span>
							</div>
							{#if canListAllUsers(session.user)}
								<label class="flex items-start gap-3 px-4 pt-3 pb-1">
									<span class="flex flex-1 flex-col gap-0.5">
										{m.all_users()}
										<span class="text-xs text-muted-foreground">{m.all_users_hint()}</span>
									</span>
									<Switch
										checked={scope.allUsers}
										onCheckedChange={(checked) => scope.set(checked)}
										class="mt-0.5"
									/>
								</label>
							{/if}
							<div class="mx-4 my-2 h-px bg-border"></div>
						{/if}
						<nav aria-label={m.nav_main()} class="flex flex-col gap-1">
							{#each workSections as section (section.path)}
								{@render pill(section, true)}
							{/each}
							<div class="mx-4 my-2 h-px bg-border"></div>
							{#each setupSections as section (section.path)}
								{@render pill(section, true)}
							{/each}
						</nav>
						{#if phone.current}
							<div class="mt-auto flex flex-col gap-1 pt-2">
								<div class="mx-4 my-2 h-px bg-border"></div>
								<div class="flex h-10 items-center justify-between gap-2 px-4">
									<span
										id="sheet-language"
										class="flex items-center gap-2.5 text-sm text-muted-foreground"
									>
										<Languages class="size-4" aria-hidden="true" />
										{m.language_label()}
									</span>
									<Segmented
										size="sm"
										labelledby="sheet-language"
										options={languageOptions}
										value={getLocale()}
										onchange={(value) => changeLanguage(value as Locale)}
									/>
								</div>
								<div class="flex h-10 items-center justify-between gap-2 px-4">
									<span
										id="sheet-theme"
										class="flex items-center gap-2.5 text-sm text-muted-foreground"
									>
										<SunMoon class="size-4" aria-hidden="true" />
										{m.theme_label()}
									</span>
									<Segmented
										size="sm"
										names="hidden"
										labelledby="sheet-theme"
										options={themeOptions}
										value={userPrefersMode.current}
										onchange={(value) => setMode(value as 'light' | 'dark' | 'system')}
									/>
								</div>
								<div class="mx-4 my-2 h-px bg-border"></div>
								<button
									type="button"
									onclick={() => open(SETTINGS)}
									class="flex h-10 items-center gap-2.5 rounded-xl px-4 text-md transition-colors hover:bg-muted"
								>
									<SETTINGS.icon class="size-4 text-muted-foreground" aria-hidden="true" />
									{SETTINGS.label()}
								</button>
								<a
									href={API_DOCS}
									target="_blank"
									rel="noopener noreferrer"
									class="flex h-10 items-center gap-2.5 rounded-xl px-4 text-md transition-colors hover:bg-muted"
								>
									<BookOpen class="size-4 text-muted-foreground" aria-hidden="true" />
									{m.api_docs()}
									<span class="sr-only">({m.opens_in_new_tab()})</span>
									<ExternalLink class="ml-auto size-4 text-muted-foreground" aria-hidden="true" />
								</a>
								<button
									type="button"
									onclick={signOut}
									class="flex h-10 items-center gap-2.5 rounded-xl px-4 text-md transition-colors hover:bg-muted"
								>
									<LogOut class="size-4 text-muted-foreground" aria-hidden="true" />
									{m.sign_out()}
								</button>
							</div>
						{/if}
					</Sheet.Content>
				</Sheet.Root>
			</div>
		</div>
	</header>

	<main
		id="main"
		tabindex="-1"
		class="flex flex-1 justify-center px-4 py-8 outline-none sm:px-8 lg:has-[[data-wide]]:min-h-0 lg:has-[[data-wide]]:py-6"
	>
		<div
			class="w-full max-w-page has-[[data-roomy]]:max-w-wide has-[[data-wide]]:max-w-wide lg:has-[[data-wide]]:min-h-0"
		>
			{@render children()}
		</div>
	</main>
</div>
