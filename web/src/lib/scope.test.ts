import { afterEach, describe, expect, it } from 'vitest';
import { scope } from './scope.svelte.ts';
import { session, type User } from './session.svelte.ts';

const user = (role: 'admin' | 'user') => ({ id: 'u1', username: 'tobi', role }) as unknown as User;

afterEach(() => {
	scope.set(false);
	session.clear();
	localStorage.clear();
});

describe('the scope setting', () => {
	it('covers all users for an admin who chose so, and is kept in this browser', () => {
		session.user = user('admin');
		expect(scope.allUsers).toBe(false);
		scope.set(true);
		expect(scope.allUsers).toBe(true);
		expect(scope.query).toBe(true);
		expect(localStorage.getItem('papiq.scope.all-users')).toBe('1');
		scope.set(false);
		expect(scope.query).toBeUndefined();
		expect(localStorage.getItem('papiq.scope.all-users')).toBeNull();
	});

	it('counts as off for anyone but an admin', () => {
		session.user = user('admin');
		scope.set(true);
		session.user = user('user');
		expect(scope.allUsers).toBe(false);
		expect(scope.query).toBeUndefined();
	});
});
