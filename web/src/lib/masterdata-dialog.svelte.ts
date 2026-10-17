/**
 * The dialogs that add and change master data, opened from anywhere: one host in the app's
 * layout shows them (`MasterDataDialogHost`). Lists watch `changed` and load again.
 */
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import type { Item, SimpleKind } from '#lib/masterdata-api.ts';

/** `any-tag`: a new tag whose kind is chosen in the dialog first. */
export type MasterDataKind = SimpleKind | 'fields' | 'any-tag';

export interface MasterDataRequest {
	kind: MasterDataKind;
	/** The item to change, or its id (it is loaded); null adds one. */
	item: Item | FieldDefinition | string | null;
	/** Opened from this rule (the rule of a type's title pattern): no link back to it. */
	fromRule: string | null;
}

class MasterDataDialogs {
	request = $state<MasterDataRequest | null>(null);
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
}

export const masterDataDialogs = new MasterDataDialogs();
