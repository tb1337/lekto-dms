/**
 * One `EventSource` on `/api/v1/events` for the signed-in session. Events are thin; pages listen
 * for the types they care about and fetch the state afresh. There is no replay: after a
 * reconnect `generation` grows and pages reload what they show. The stream ends on sign-out.
 */
import { BASE_API } from '#lib/api/base.ts';

/** The events about a document; webhooks choose from these. */
export const DOCUMENT_EVENT_TYPES = [
	'document.received',
	'document.node_started',
	'document.node_deferred',
	'document.node_completed',
	'document.lane_changed',
	'document.filed',
	'document.updated',
	'document.deleted'
] as const;
export type DocumentEventType = (typeof DOCUMENT_EVENT_TYPES)[number];

/** The events without a document for every user: a new model of the classifier. */
export const SYSTEM_EVENT_TYPES = ['classifier.trained'] as const;
export type SystemEventType = (typeof SYSTEM_EVENT_TYPES)[number];

/** The events of the caller's own searches: the meaning of a query is ready (`query`). */
export const SEARCH_EVENT_TYPES = ['search.meaning_ready'] as const;
export type SearchEventType = (typeof SEARCH_EVENT_TYPES)[number];

/** Events about a node of the graph: how far processing is, not where a document stands. */
// eslint-disable-next-line svelte/prefer-svelte-reactivity -- never changes
export const NODE_EVENTS: ReadonlySet<DocumentEventType> = new Set<DocumentEventType>([
	'document.node_started',
	'document.node_deferred',
	'document.node_completed'
]);

export interface DocumentEvent {
	type: DocumentEventType;
	id: string;
	occurred_at: string;
	document_id: string;
	[key: string]: unknown;
}

/** `classifier.trained`: `number` and `examples` of the new model; `search.meaning_ready`:
 * `query`. */
export interface AdminEvent {
	type: SystemEventType | SearchEventType;
	id: string;
	occurred_at: string;
	[key: string]: unknown;
}

type Handler = (event: DocumentEvent) => void;
type AdminHandler = (event: AdminEvent) => void;

class EventStream {
	/** Grows with every reconnect after a break: shown data may be stale. */
	generation = $state(0);
	connected = $state(false);
	#source: EventSource | null = null;
	#handlers = new Set<Handler>();
	#adminHandlers = new Set<{ type: SystemEventType | SearchEventType; handler: AdminHandler }>();
	// Whether a stream was open before: every later `onopen` is a reconnect (after a network
	// break, or after the server closed the stream and the caller started it again).
	#opened = false;
	#factory: (url: string) => EventSource = (url) => new EventSource(url);

	/** For tests. */
	useFactory(factory: (url: string) => EventSource): void {
		this.#factory = factory;
	}

	/** Listen to all document events; returns the function that stops listening. */
	subscribe(handler: Handler): () => void {
		this.#handlers.add(handler);
		return () => this.#handlers.delete(handler);
	}

	/** Listen to one of the events without a document (an admin's, a search's); returns the
	 * function that stops listening. */
	on(type: SystemEventType | SearchEventType, handler: AdminHandler): () => void {
		const entry = { type, handler };
		this.#adminHandlers.add(entry);
		return () => this.#adminHandlers.delete(entry);
	}

	/**
	 * Open the stream. `onClosed` is called when the browser gave up on it (the API answered with
	 * an error, e.g. 401 after the session ended); the caller decides whether to start again.
	 */
	start(onClosed: () => void): void {
		if (this.#source) return;
		const source = this.#factory(`${BASE_API}/events`);
		this.#source = source;
		source.onopen = () => {
			this.connected = true;
			if (this.#opened) this.generation++;
			this.#opened = true;
		};
		source.onerror = () => {
			this.connected = false;
			// Network breaks are retried by the browser itself; a closed source is not.
			if (source.readyState === 2) {
				this.stop();
				onClosed();
			}
		};
		for (const type of DOCUMENT_EVENT_TYPES) {
			source.addEventListener(type, (message) => {
				const event = parsed<DocumentEvent>(message);
				if (event) for (const handler of this.#handlers) handler(event);
			});
		}
		for (const type of [...SYSTEM_EVENT_TYPES, ...SEARCH_EVENT_TYPES]) {
			source.addEventListener(type, (message) => {
				const event = parsed<AdminEvent>(message);
				if (!event) return;
				for (const entry of this.#adminHandlers) if (entry.type === type) entry.handler(event);
			});
		}
	}

	stop(): void {
		this.#source?.close();
		this.#source = null;
		this.connected = false;
	}
}

/** The event of a message; null for a malformed one (the next reconnect reloads anyway). */
function parsed<T>(message: Event): T | null {
	try {
		return JSON.parse((message as MessageEvent<string>).data) as T;
	} catch {
		return null;
	}
}

export const events = new EventStream();
