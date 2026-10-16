import { redirect } from '@sveltejs/kit';
import { BASE } from '#lib/base.ts';

// The start page is the inbox: what waits for a decision comes first.
export function load() {
	redirect(307, `${BASE}/inbox`);
}
