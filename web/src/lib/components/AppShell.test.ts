import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LANGUAGE_NAMES, locales } from '#lib/i18n.ts';
import { inbox } from '#lib/inbox.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { scope } from '#lib/scope.svelte.ts';
import { SETTINGS } from '#lib/sections.ts';
import { session, type User } from '#lib/session.svelte.ts';
import AppShell from './AppShell.svelte';

vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/state', () => ({ page: { url: new URL('http://lekto/ui/inbox'), state: {} } }));

const children = createRawSnippet(() => ({ render: () => '<p>content</p>' }));

function signIn(role: User['role']) {
	session.start({
		user: { id: '0199a6c4-0000-7000-8000-000000000001', username: 'tobi', role },
		method: 'password',
		expires_at: '2026-10-09T12:00:00Z',
		csrf_token: 'token'
	});
}

afterEach(async () => {
	session.clear();
	phone.override(null);
	scope.set(false);
	// The shell reacts to the reach in an effect: let it run while the spies still stand.
	await tick();
	inbox.summary = null;
	vi.restoreAllMocks();
});

function mainNavigation() {
	// The header holds the wide navigation; the narrow one lives in a closed sheet.
	return screen.getByRole('navigation', { name: m.nav_main() });
}

/** The account menu; bits-ui opens it on a pointer press. */
async function openAccountMenu(): Promise<HTMLElement> {
	await fireEvent.pointerDown(
		screen.getByRole('button', { name: m.account_menu({ username: 'tobi' }) }),
		{
			button: 0,
			pointerType: 'mouse'
		}
	);
	return screen.findByRole('menu');
}

describe('AppShell', () => {
	it('shows users their areas without the admin areas', () => {
		signIn('user');
		render(AppShell, { children });
		const nav = mainNavigation();
		expect(within(nav).getByRole('link', { name: m.nav_documents() })).toBeTruthy();
		expect(within(nav).queryByRole('link', { name: m.nav_users() })).toBeNull();
		expect(within(nav).queryByRole('link', { name: m.nav_master_data() })).toBeNull();
	});

	it('shows admins the admin areas', () => {
		signIn('admin');
		render(AppShell, { children });
		const nav = mainNavigation();
		expect(within(nav).getByRole('link', { name: m.nav_users() }).getAttribute('href')).toBe(
			'/ui/admin/users'
		);
		expect(within(nav).getByRole('link', { name: m.nav_master_data() })).toBeTruthy();
	});

	it('marks the current area', () => {
		signIn('user');
		render(AppShell, { children });
		const inbox = within(mainNavigation()).getByRole('link', { name: m.nav_inbox() });
		expect(inbox.getAttribute('aria-current')).toBe('page');
	});

	it('lists the inbox first and offers the search in the header', () => {
		signIn('admin');
		render(AppShell, { children });
		const links = within(mainNavigation()).getAllByRole('link');
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/ui/inbox',
			'/ui/documents',
			'/ui/spaces',
			'/ui/rules',
			'/ui/webhooks',
			'/ui/admin/master-data',
			'/ui/admin/users',
			'/ui/system'
		]);
		expect(screen.getByRole('search')).toBeTruthy();
		expect(screen.getByRole('searchbox', { name: m.header_search_label() })).toBeTruthy();
	});

	it('separates the work from running Lekto, also for users', () => {
		signIn('user');
		render(AppShell, { children });
		const nav = mainNavigation();
		const links = within(nav).getAllByRole('link');
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/ui/inbox',
			'/ui/documents',
			'/ui/spaces',
			'/ui/rules',
			'/ui/webhooks',
			'/ui/system'
		]);
		// The line stands after the webhooks (Tobi, 27.10.2026).
		const line = nav.querySelector('[data-slot="separator"]');
		expect(line?.previousElementSibling?.getAttribute('href')).toBe('/ui/webhooks');
		// Below xl the second group stands behind "More"; from xl each link (in its wrapper).
		const next = line?.nextElementSibling;
		expect((next?.matches('a') ? next : next?.querySelector('a'))?.getAttribute('href')).toBe(
			'/ui/system'
		);
	});

	it('shows the logo with its icon', () => {
		signIn('user');
		render(AppShell, { children });
		const logo = screen.getByRole('img', { name: m.app_name() });
		expect(logo.querySelector('svg')).toBeTruthy();
		expect(logo.textContent?.trim()).toBe('lekto');
	});

	it('counts what is open in the inbox, coloured by the worst lane', async () => {
		signIn('user');
		inbox.summary = {
			new: 1,
			review: 2,
			intervene: 1,
			processing: 1,
			done: 7,
			open: 5,
			worst_lane: 'red'
		};
		render(AppShell, { children });
		const label = [
			m.inbox_badge_total({ count: 5 }),
			m.inbox_badge_red({ count: 1 }),
			m.inbox_badge_yellow({ count: 2 }),
			m.inbox_badge_new({ count: 1 }),
			m.inbox_badge_processing({ count: 1 })
		].join(', ');
		const badge = within(mainNavigation()).getByRole('img', { name: label });
		expect(badge.textContent?.trim()).toBe('5');
		expect(badge.dataset.tone).toBe('red');
		expect(badge.className).toContain('bg-lane-red');
		expect(badge.className).toContain('text-lane-red-foreground');

		inbox.summary = {
			...inbox.summary,
			intervene: 0,
			review: 0,
			new: 0,
			open: 1,
			worst_lane: null
		};
		await tick();
		const grey = within(mainNavigation()).getByRole('img', {
			name: `${m.inbox_badge_total({ count: 1 })}, ${m.inbox_badge_processing({ count: 1 })}`
		});
		expect(grey.dataset.tone).toBe('grey');
		expect(grey.className).toContain('bg-lane-running');

		inbox.summary = { ...inbox.summary, processing: 0, open: 0 };
		await tick();
		expect(within(mainNavigation()).queryByRole('img')).toBeNull();
	});

	it('counts the inbox anew when the reach switches, not on first sight', async () => {
		signIn('admin');
		const refresh = vi.spyOn(inbox, 'refresh').mockResolvedValue();
		render(AppShell, { children });
		await tick();
		expect(refresh).not.toHaveBeenCalled();
		scope.set(true);
		await tick();
		expect(refresh).toHaveBeenCalledOnce();
	});

	it('offers a skip link and the account menu', () => {
		signIn('user');
		render(AppShell, { children });
		expect(screen.getByRole('link', { name: m.skip_to_content() }).getAttribute('href')).toBe(
			'#main'
		);
		expect(screen.getByRole('button', { name: m.account_menu({ username: 'tobi' }) })).toBeTruthy();
		expect(screen.getByText('content')).toBeTruthy();
	});

	it('keeps language and theme in the account menu (web/DESIGN.md, "Navigation")', async () => {
		phone.override(false);
		signIn('user');
		render(AppShell, { children });
		expect(screen.queryByRole('button', { name: m.theme_label() })).toBeNull();
		const menu = await openAccountMenu();
		expect(within(menu).getAllByRole('menuitemradio').length).toBeGreaterThanOrEqual(5);
		expect(within(menu).getByText(m.theme_label())).toBeTruthy();
		expect(within(menu).getByText(m.language_label())).toBeTruthy();
	});

	it('moves the account into the navigation sheet on a phone', async () => {
		phone.override(true);
		signIn('admin');
		render(AppShell, { children });
		expect(screen.queryByRole('button', { name: m.theme_label() })).toBeNull();
		expect(screen.queryByRole('button', { name: /^Sprache|^Language/ })).toBeNull();
		expect(screen.queryByRole('button', { name: m.account_menu({ username: 'tobi' }) })).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: m.nav_open() }));
		const sheet = await screen.findByRole('dialog');
		expect(within(sheet).getByText('tobi')).toBeTruthy();
		expect(within(sheet).getByText(m.role_admin())).toBeTruthy();
		expect(within(sheet).getByRole('switch', { name: new RegExp(m.all_users()) })).toBeTruthy();
		const links = within(sheet).getAllByRole('link');
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/ui/inbox',
			'/ui/documents',
			'/ui/spaces',
			'/ui/rules',
			'/ui/webhooks',
			'/ui/admin/master-data',
			'/ui/admin/users',
			'/ui/system',
			'/api/v1/docs'
		]);
		const language = within(sheet).getByRole('group', { name: m.language_label() });
		expect(
			within(language)
				.getAllByRole('button')
				.map((b) => b.textContent?.trim())
		).toEqual(locales.map((locale) => LANGUAGE_NAMES[locale]));
		const theme = within(sheet).getByRole('group', { name: m.theme_label() });
		expect(
			within(theme)
				.getAllByRole('button')
				.map((b) => b.getAttribute('aria-label'))
		).toEqual([m.theme_light(), m.theme_dark(), m.theme_system()]);
		expect(within(sheet).getByRole('button', { name: SETTINGS.label() })).toBeTruthy();
		expect(within(sheet).getByRole('button', { name: m.sign_out() })).toBeTruthy();
	});

	it('keeps the sheet to the navigation on a tablet, and the account in the header', async () => {
		phone.override(false);
		signIn('user');
		render(AppShell, { children });
		expect(screen.getByRole('button', { name: m.account_menu({ username: 'tobi' }) })).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: m.nav_open() }));
		const sheet = await screen.findByRole('dialog');
		expect(within(sheet).queryByText('tobi')).toBeNull();
		expect(within(sheet).queryByRole('button', { name: m.sign_out() })).toBeNull();
		expect(within(sheet).getAllByRole('link')).toHaveLength(6);
	});

	it('marks the menu button on a phone when an admin sees all users', async () => {
		phone.override(true);
		signIn('admin');
		scope.set(true);
		render(AppShell, { children });
		expect(screen.getByRole('button', { name: m.nav_open_all_users() })).toBeTruthy();
		scope.set(false);
		await tick();
		expect(screen.getByRole('button', { name: m.nav_open() })).toBeTruthy();
	});

	it('links the API documentation from the account menu, in a new tab', async () => {
		signIn('user');
		render(AppShell, { children });
		const menu = await openAccountMenu();
		const docs = within(menu).getByRole('menuitem', {
			name: `${m.api_docs()} (${m.opens_in_new_tab()})`
		});
		expect(docs.tagName).toBe('A');
		expect(docs.getAttribute('href')).toBe('/api/v1/docs');
		expect(docs.getAttribute('target')).toBe('_blank');
		expect(docs.getAttribute('rel')).toBe('noopener noreferrer');
	});
});
