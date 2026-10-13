import { describe, expect, it } from 'vitest';
import { href, isCurrent, SECTIONS, visibleSections } from './sections.ts';

describe('visibleSections', () => {
	it('hides the admin areas from users', () => {
		const paths = visibleSections(false).map((section) => section.path);
		expect(paths).not.toContain('/admin/users');
		expect(paths).not.toContain('/admin/master-data');
		expect(paths).toContain('/documents');
	});

	it('shows everything to admins', () => {
		expect(visibleSections(true)).toEqual(SECTIONS);
	});
});

describe('SECTIONS', () => {
	it('starts with the inbox, the search is not among them', () => {
		const paths = SECTIONS.map((section) => section.path);
		expect(paths.slice(0, 2)).toEqual(['/inbox', '/documents']);
		expect(paths).not.toContain('/search');
		expect(paths.slice(-2)).toEqual(['/admin/master-data', '/admin/users']);
	});
});

describe('isCurrent', () => {
	const documents = SECTIONS.find((section) => section.path === '/documents')!;

	it('matches the section and pages below it', () => {
		expect(href(documents)).toBe('/ui/documents');
		expect(isCurrent(documents, '/ui/documents')).toBe(true);
		expect(isCurrent(documents, '/ui/documents/42')).toBe(true);
		expect(isCurrent(documents, '/ui/documentsx')).toBe(false);
	});
});
