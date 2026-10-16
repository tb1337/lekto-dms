import { redirect } from '@sveltejs/kit';
import { BASE } from '#lib/base.ts';
import type { PageLoad } from './$types';

// The inbox opens a document in the document view, which keeps its place among the inbox's.
export const load: PageLoad = ({ params }) => {
	redirect(307, `${BASE}/documents/${params.id}?from=inbox`);
};
