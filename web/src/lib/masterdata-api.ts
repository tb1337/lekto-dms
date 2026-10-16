/** Create, change and delete for the three simple kinds of master data. */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { IdentifierIn, IdentifierOut } from '#lib/identifiers.ts';
import type { MasterData } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type SimpleKind = 'contacts' | 'document-types' | 'tags';

/** A contact's aliases or a document type's description; tags have neither. */
export type Extra = 'aliases' | 'description' | null;

/** One item as listed: contacts carry aliases and identifiers, document types a description. */
export type Item = MasterData & {
	aliases?: string[];
	identifiers?: IdentifierOut[];
	description?: string | null;
	title_pattern?: string | null;
	/** With `ListOptions.counts`: how many documents (in the scope) have it. */
	document_count?: number | null;
};

/** A list may count the documents of each item, within the caller's reach or of all users. */
export interface ListOptions {
	counts?: boolean;
	allUsers?: boolean;
}

const listQuery = (options: ListOptions = {}) => ({
	params: {
		query: {
			document_counts: options.counts || undefined,
			all_users: options.allUsers || undefined
		}
	}
});

/** What a dialog edits: the name and, by kind, aliases and identifiers or a description. */
export interface Values {
	name: string;
	aliases: string[];
	identifiers: IdentifierIn[];
	rejected_identifiers: IdentifierIn[];
	description: string | null;
	title_pattern: string | null;
	/** A document type's fields, global ones aside; null where they do not change. */
	fields: { id: string; required: boolean }[] | null;
}

export interface KindOps {
	title: () => string;
	add: () => string;
	extra: Extra;
	/** The parameter of the document view that filters by an item. */
	filter: 'contact' | 'type' | 'tag';
	list(options?: ListOptions): Promise<Item[]>;
	get(id: string): Promise<Item>;
	create(values: Values): Promise<Item>;
	change(id: string, values: Values): Promise<unknown>;
	remove(id: string): Promise<unknown>;
}

const path = (id: string) => ({ params: { path: { id } } });

export const KINDS: Record<SimpleKind, KindOps> = {
	contacts: {
		title: m.master_contacts,
		add: m.master_add_contact,
		extra: 'aliases',
		filter: 'contact',
		list: (options) => unwrap(api.GET('/api/v1/contacts', listQuery(options))),
		get: (id) => unwrap(api.GET('/api/v1/contacts/{id}', path(id))),
		create: ({ name, aliases, identifiers }) =>
			unwrap(api.POST('/api/v1/contacts', { body: { name, aliases, identifiers } })),
		change: (id, { name, aliases, identifiers, rejected_identifiers }) =>
			unwrap(
				api.PATCH('/api/v1/contacts/{id}', {
					...path(id),
					body: { name, aliases, identifiers, rejected_identifiers }
				})
			),
		remove: (id) => unwrap(api.DELETE('/api/v1/contacts/{id}', path(id)))
	},
	'document-types': {
		title: m.master_types,
		add: m.master_add_type,
		extra: 'description',
		filter: 'type',
		list: (options) => unwrap(api.GET('/api/v1/document-types', listQuery(options))),
		get: (id) => unwrap(api.GET('/api/v1/document-types/{id}', path(id))),
		create: ({ name, description, title_pattern }) =>
			unwrap(api.POST('/api/v1/document-types', { body: { name, description, title_pattern } })),
		change: (id, { name, description, title_pattern }) =>
			unwrap(
				api.PATCH('/api/v1/document-types/{id}', {
					...path(id),
					body: { name, description, title_pattern }
				})
			),
		remove: (id) => unwrap(api.DELETE('/api/v1/document-types/{id}', path(id)))
	},
	tags: {
		title: m.master_tags,
		add: m.master_add_tag,
		extra: null,
		filter: 'tag',
		list: (options) => unwrap(api.GET('/api/v1/tags', listQuery(options))),
		get: (id) => unwrap(api.GET('/api/v1/tags/{id}', path(id))),
		create: ({ name }) => unwrap(api.POST('/api/v1/tags', { body: { name } })),
		change: (id, { name }) =>
			unwrap(api.PATCH('/api/v1/tags/{id}', { ...path(id), body: { name } })),
		remove: (id) => unwrap(api.DELETE('/api/v1/tags/{id}', path(id)))
	}
};

/** One alias per line; empty lines dropped. */
export function parseAliases(text: string): string[] {
	return text
		.split('\n')
		.map((line) => line.trim())
		.filter((line) => line !== '');
}
