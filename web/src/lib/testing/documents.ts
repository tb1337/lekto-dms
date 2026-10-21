/**
 * Builders for tests of documents and the inbox, and a fake of the API that answers by method
 * and path.
 */
import { vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';

type Document = components['schemas']['DocumentDetails'];
type Listed = components['schemas']['ListedDocument'];
type InboxItem = components['schemas']['InboxItemOut'];
type InboxTab = components['schemas']['InboxTab'];
type Summary = components['schemas']['InboxSummaryOut'];
type Processing = components['schemas']['Processing'];

export const OWNER = 'user-1';

/** Processing ended (`run` 1, every node done) or, with `running`, at the text recognition. */
export function processingOf(running = false): Processing {
	return {
		status: running ? 'processing' : 'completed',
		run: 1,
		vision: false,
		nodes: [
			{ node: 'receive', status: 'done', outcome: 'ok', started_at: null, finished_at: null },
			{
				node: 'ocr',
				status: running ? 'running' : 'done',
				outcome: running ? null : 'ok',
				started_at: null,
				finished_at: null
			}
		]
	} as Processing;
}

export function documentOf(changes: Partial<Document> = {}): Document {
	return {
		id: 'doc-1',
		title: 'Stromrechnung',
		original_filename: 'scan.pdf',
		media_type: 'application/pdf',
		channel: 'web',
		sha256: 'a'.repeat(64),
		uploaded_by: OWNER,
		space_id: 'space-1',
		access: 'edit',
		contact_id: null,
		document_type_id: null,
		topic_id: null,
		tag_ids: [],
		document_date: null,
		fields: {},
		lane: 'green',
		page_count: 1,
		confirmed_at: null,
		processing: processingOf(changes.lane === null),
		created_at: '2026-10-18T08:00:00Z',
		updated_at: '2026-10-18T08:00:00Z',
		...changes
	};
}

export function listedOf(changes: Partial<Listed> = {}): Listed {
	return { ...documentOf(changes), in_inbox: false, ...changes };
}

const LANES: Record<InboxTab, Document['lane']> = {
	new: 'green',
	review: 'yellow',
	intervene: 'red',
	processing: null,
	done: 'green'
};

/** A document of the inbox under `tab`; done ones seen by the owner unless `done` says. */
export function inboxItem(
	tab: InboxTab,
	document: Partial<Document> = {},
	extra: Partial<InboxItem> = {}
): InboxItem {
	return {
		document: documentOf({ lane: LANES[tab], ...document }),
		tab,
		open: [],
		done: tab === 'done' ? { how: 'seen', at: '2026-10-18T09:30:00Z', by: OWNER } : null,
		...extra
	};
}

/** The summary of an inbox with these counts; open and the worst lane follow from them. */
export function summaryOf(counts: Partial<Summary> = {}): Summary {
	const base = { new: 0, review: 0, intervene: 0, processing: 0, done: 0, ...counts };
	return {
		...base,
		open: base.new + base.review + base.intervene + base.processing,
		worst_lane: base.intervene ? 'red' : base.review ? 'yellow' : base.new ? 'green' : null,
		...counts
	};
}

export function json(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': status < 400 ? 'application/json' : 'application/problem+json' }
	});
}

type Answer = unknown | Response | Promise<unknown | Response>;
type Route = (request: Request, url: URL) => Answer;

/**
 * A fetch that answers by `METHOD /path` (`GET /api/v1/inbox`): JSON of what the route returns,
 * or its response. Without a route a GET answers an empty list (the master data), anything
 * else 204. Stub it with `vi.stubGlobal('fetch', …)`.
 */
export function fakeApi(routes: Record<string, Route> = {}) {
	return vi.fn(async (request: Request) => {
		const url = new URL(request.url);
		const route = routes[`${request.method} ${url.pathname}`];
		if (!route) return request.method === 'GET' ? json([]) : new Response(null, { status: 204 });
		const answer = await route(request, url);
		return answer instanceof Response ? answer : json(answer);
	});
}

/** The requests a fake API received, as `METHOD /path?query`. */
export function calls(api: ReturnType<typeof fakeApi>): string[] {
	return api.mock.calls.map(([request]) => {
		const url = new URL(request.url);
		return `${request.method} ${url.pathname}${url.search}`;
	});
}
