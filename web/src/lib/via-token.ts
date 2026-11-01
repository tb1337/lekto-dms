/**
 * A decision through an API token names the token after the person (DESIGN.md, Names of
 * people): "Tobi über Token „Claude“". The API sends the token's name as it was then, so it
 * stays readable once the token is renamed or revoked.
 */
import { m } from '#lib/paraglide/messages.js';
import { object } from '#lib/signals.ts';

/** The name of the API token a log entry's input or output names (`via_token`); null for an
 * entry written in the web UI or before tokens were kept. */
export function tokenOf(part: unknown): string | null {
	const name = object(object(part).via_token).name;
	return typeof name === 'string' && name ? name : null;
}

/** `name` with the API token the person acted through, if any. */
export function viaToken(name: string, token: string | null | undefined): string {
	return token ? m.by_token({ name, token }) : name;
}
