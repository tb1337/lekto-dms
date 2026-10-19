/**
 * The reach of the lists for admins: their own documents, inbox and rules, or those of all
 * users. A setting of this browser, from the user menu; kept across sign-ins. The API decides
 * who may ask for all users (`all_users`); for anyone but an admin the setting counts as off.
 */
import { canListAllUsers } from '#lib/permissions.ts';
import { session } from '#lib/session.svelte.ts';

const KEY = 'lekto.scope.all-users';

function stored(): boolean {
	try {
		return globalThis.localStorage?.getItem(KEY) === '1';
	} catch {
		return false; // no storage (private window, blocked site data): off
	}
}

class Scope {
	#chosen = $state(stored());

	/** Whether the lists cover all users: an admin chose so. */
	get allUsers(): boolean {
		return this.#chosen && canListAllUsers(session.user);
	}

	/** The query parameter of the API: present only when on. */
	get query(): true | undefined {
		return this.allUsers || undefined;
	}

	set(allUsers: boolean): void {
		this.#chosen = allUsers;
		try {
			if (allUsers) globalThis.localStorage?.setItem(KEY, '1');
			else globalThis.localStorage?.removeItem(KEY);
		} catch {
			// Kept for this page only.
		}
	}
}

export const scope = new Scope();
