import { describe, expect, it } from 'vitest';
import { httpUrl } from './http-url.ts';

describe('a web address to send the browser to', () => {
	it('takes http and https, absolute or relative to the page', () => {
		expect(httpUrl('https://idp.example/auth?x=1', 'http://lekto')).toBe(
			'https://idp.example/auth?x=1'
		);
		expect(httpUrl('/api/v1/auth/oidc/start', 'http://lekto')).toBe(
			'http://lekto/api/v1/auth/oidc/start'
		);
	});

	it('refuses every other scheme and garbage', () => {
		expect(httpUrl('javascript:alert(1)', 'http://lekto')).toBeNull();
		expect(httpUrl('data:text/html,hi', 'http://lekto')).toBeNull();
		expect(httpUrl('http://[bad', 'http://lekto')).toBeNull();
		expect(httpUrl('', 'not a base')).toBeNull();
	});
});
