/**
 * Saving a rule switched off (decision E2): the person sees what it would do on the documents
 * there are before switching it on. A new rule is created switched off, a changed one saved
 * switched off, each in one request (`enabled: false`): it never runs in between (issue #73;
 * until then a new rule was switched off in a second request, F5a).
 */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';
import type { ApiDefinition } from '#lib/rules/model.ts';

type Rule = components['schemas']['RuleOut'];

/** Where a new rule belongs: `global`, or the id of its space. */
export const GLOBAL = 'global';

export async function createSwitchedOff(place: string, definition: ApiDefinition): Promise<Rule> {
	const body =
		place === GLOBAL
			? { scope: 'global' as const, ...definition }
			: { scope: 'space' as const, space_id: place, ...definition };
	return unwrap(api.POST('/api/v1/rules', { body: { ...body, enabled: false } }));
}

/** `place`: where the rule moves (`GLOBAL` or a space id); none: it stays where it is. */
export async function changeSwitchedOff(
	rule: Rule,
	definition: ApiDefinition,
	place?: string
): Promise<Rule> {
	const body =
		place === undefined
			? definition
			: place === GLOBAL
				? { ...definition, scope: 'global' as const }
				: { ...definition, scope: 'space' as const, space_id: place };
	return unwrap(
		api.PUT('/api/v1/rules/{id}', {
			params: { path: { id: rule.id } },
			body: { ...body, enabled: false }
		})
	);
}
