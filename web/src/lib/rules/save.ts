/**
 * Saving a rule switched off (decision E2): the person sees what it would do on the documents
 * there are before switching it on. A new rule is created and switched off at once (the API
 * creates rules switched on; the moment between is accepted, F5a). A changed rule is switched
 * off first and on again if the change fails (if that fails too, the person is told).
 */
import { toast } from 'svelte-sonner';
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import type { ApiDefinition } from '#lib/rules/model.ts';

type Rule = components['schemas']['RuleOut'];

function setEnabled(id: string, enabled: boolean): Promise<Rule> {
	return unwrap(api.PATCH('/api/v1/rules/{id}', { params: { path: { id } }, body: { enabled } }));
}

/** Where a new rule belongs: `global`, or the id of its space. */
export const GLOBAL = 'global';

export async function createSwitchedOff(place: string, definition: ApiDefinition): Promise<Rule> {
	const body =
		place === GLOBAL
			? { scope: 'global' as const, ...definition }
			: { scope: 'space' as const, space_id: place, ...definition };
	const created = await unwrap(api.POST('/api/v1/rules', { body }));
	return setEnabled(created.id, false);
}

export async function changeSwitchedOff(rule: Rule, definition: ApiDefinition): Promise<Rule> {
	if (rule.enabled) await setEnabled(rule.id, false);
	try {
		return await unwrap(
			api.PUT('/api/v1/rules/{id}', { params: { path: { id: rule.id } }, body: definition })
		);
	} catch (error) {
		if (rule.enabled) await setEnabled(rule.id, true).catch(() => toast.warning(m.rule_left_off()));
		throw error;
	}
}
