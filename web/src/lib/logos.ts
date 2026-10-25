/** Logos of contacts: whether the server fetches them (from `GET /pipeline`), and uploading,
 * removing and fetching one. */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { Contact } from '#lib/masterdata.svelte.ts';
import { pipeline } from '#lib/pipeline.ts';

/** Whether Lekto fetches logos from websites (`LEKTO_LOGO_FETCH`); false if it cannot tell. */
export function logoFetching(): Promise<boolean> {
	return pipeline().then(
		(found) => found.logo_fetch,
		() => false
	);
}

/** The contact's domains among its identifiers that count: where its website is. */
export function domainsOf(contact: Pick<Contact, 'identifiers'>): string[] {
	return contact.identifiers
		.filter((item) => item.kind === 'email_domain' && item.source !== 'rejected')
		.map((item) => item.value);
}

export async function uploadLogo(id: string, file: File): Promise<Contact> {
	const form = new FormData();
	form.append('file', file);
	return unwrap(
		api.PUT('/api/v1/contacts/{id}/logo', {
			params: { path: { id } },
			// The generated type wants a string for the file; the form carries the binary.
			body: { file: '' },
			bodySerializer: () => form
		})
	);
}

export async function removeLogo(id: string): Promise<void> {
	await unwrap(api.DELETE('/api/v1/contacts/{id}/logo', { params: { path: { id } } }));
}

export async function fetchLogo(id: string): Promise<void> {
	await unwrap(api.POST('/api/v1/contacts/{id}/logo/fetch', { params: { path: { id } } }));
}
