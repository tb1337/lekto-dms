/**
 * The dialogs that add and change master data, opened from anywhere: one host in the app's
 * layout shows them (`MasterDataDialogHost`). Lists watch `changed` and load again. A picker
 * makes a contact, type or tag in a dialog over the page or the dialog it is in (`create`),
 * the name it searched for filled in, and gets back what was made; these dialogs stack (a
 * contact made from a document may make a group of its own).
 */
import type { FieldDefinition, Tag, TagScope } from '#lib/masterdata.svelte.ts';
import { kindOfScope, type Item, type SimpleKind } from '#lib/masterdata-api.ts';

/** `any-tag`: a new tag whose kind is chosen in the dialog first. */
export type MasterDataKind = SimpleKind | 'fields' | 'any-tag';

export interface MasterDataRequest {
	kind: MasterDataKind;
	/** The item to change, or its id (it is loaded); null adds one. */
	item: Item | FieldDefinition | string | null;
	/** Opened from this rule (the rule of a type's title pattern): no link back to it. */
	fromRule: string | null;
}

/** Something to make with its details over the page or dialog a picker is in: of `kind`,
 * named `name` for a start; `resolve` gets what was made, or null. */
export interface CreateRequest {
	kind: SimpleKind;
	name: string;
	resolve: (item: Item | null) => void;
}

class MasterDataDialogs {
	request = $state<MasterDataRequest | null>(null);
	/** The dialogs that make something for a picker, the last on top. */
	nested = $state.raw<CreateRequest[]>([]);
	/** Counts saves; a list that shows master data loads again when it changes. */
	changed = $state(0);

	open(
		kind: MasterDataKind,
		item: Item | FieldDefinition | string | null = null,
		options: { fromRule?: string } = {}
	) {
		this.request = { kind, item, fromRule: options.fromRule ?? null };
	}

	close() {
		this.request = null;
	}

	saved() {
		this.changed += 1;
	}

	/** A dialog of `kind` over the current one, the name filled in: what it made, or null
	 * once it closes without. */
	create(kind: SimpleKind, name: string): Promise<Item | null> {
		return new Promise((resolve) => {
			this.nested = [...this.nested, { kind, name: name.trim(), resolve }];
		});
	}

	/** The tag dialog of `scope` over the current one (`create`). */
	createTag(scope: TagScope, name: string): Promise<Tag | null> {
		return this.create(kindOfScope(scope), name) as Promise<Tag | null>;
	}

	/** The dialog of `request` (the one on top) closed: with what it made, or without (null). */
	finish(item: Item | null, request: CreateRequest | undefined = this.nested.at(-1)) {
		if (!request || !this.nested.includes(request)) return;
		this.nested = this.nested.filter((entry) => entry !== request);
		request.resolve(item);
	}

	/** Every dialog that makes something closed, without (tests start afresh). */
	finishAll() {
		while (this.nested.length > 0) this.finish(null);
	}
}

export const masterDataDialogs = new MasterDataDialogs();
