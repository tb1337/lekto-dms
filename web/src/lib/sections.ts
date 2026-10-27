import type { Component } from 'svelte';
import Activity from '@lucide/svelte/icons/activity';
import Archive from '@lucide/svelte/icons/archive';
import CalendarClock from '@lucide/svelte/icons/calendar-clock';
import FileText from '@lucide/svelte/icons/file-text';
import Inbox from '@lucide/svelte/icons/inbox';
import Settings from '@lucide/svelte/icons/settings';
import Tags from '@lucide/svelte/icons/tags';
import Users from '@lucide/svelte/icons/users';
import Webhook from '@lucide/svelte/icons/webhook';
import Workflow from '@lucide/svelte/icons/workflow';
import { BASE } from '#lib/base.ts';
import { m } from '#lib/paraglide/messages.js';

/** An area of the app. `admin` areas are hidden for other users; the API checks the rights. */
export interface Section {
	path: string;
	label: () => string;
	icon: Component;
	admin: boolean;
	/** The menu's two groups, a line between them (Tobi, 26.10.2026): the work, and setting up
	 * and running Lekto. Not who may see the area: `admin` says that. */
	group: 'work' | 'setup';
}

// The search is the field in the header and in the document view, not an area of its own
// (Tobi, 13.10.2026; one view with the documents since 16.10.2026).
export const SECTIONS: readonly Section[] = [
	{ path: '/inbox', label: m.nav_inbox, icon: Inbox, admin: false, group: 'work' },
	{ path: '/documents', label: m.nav_documents, icon: FileText, admin: false, group: 'work' },
	// The documents expected next by their series (#145).
	{ path: '/expected', label: m.nav_expected, icon: CalendarClock, admin: false, group: 'work' },
	{ path: '/spaces', label: m.nav_spaces, icon: Archive, admin: false, group: 'work' },
	{ path: '/rules', label: m.nav_rules, icon: Workflow, admin: false, group: 'setup' },
	{ path: '/webhooks', label: m.nav_webhooks, icon: Webhook, admin: false, group: 'setup' },
	// Classifier, search index and jobs for everyone; acting on them is for admins (Tobi,
	// 24.10.2026).
	{ path: '/system', label: m.nav_system, icon: Activity, admin: false, group: 'setup' },
	{ path: '/admin/master-data', label: m.nav_master_data, icon: Tags, admin: true, group: 'setup' },
	{ path: '/admin/users', label: m.nav_users, icon: Users, admin: true, group: 'setup' }
];

export const SETTINGS: Section = {
	path: '/settings',
	label: m.nav_settings,
	icon: Settings,
	admin: false,
	group: 'setup'
};

/** The areas this user sees: all for admins, the others without the admin areas. */
export function visibleSections(isAdmin: boolean): Section[] {
	return SECTIONS.filter((section) => isAdmin || !section.admin);
}

export function href(section: Section): string {
	return `${BASE}${section.path}`;
}

/** Whether `pathname` lies in the section. */
export function isCurrent(section: Section, pathname: string): boolean {
	const target = href(section);
	return pathname === target || pathname.startsWith(`${target}/`);
}
