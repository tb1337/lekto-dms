/**
 * The Beam (web/DESIGN.md, "Beam"): a sheet from the right that shows a document's pages
 * without leaving the place. Its state lives in the history entry (`page.state.beam`, ids
 * only; `history-state.ts`): the back button closes it, a reload brings it back, paging through
 * its documents replaces the entry.
 */
import { page } from '$app/state';
import type { IdentifierKind } from '#lib/identifiers.ts';
import { dropEntry, pushEntry, replaceEntry } from '#lib/history-state.ts';

/** Where the places the Beam marks come from: an open identifier's detail
 * (`GET /identifiers/open/{kind}/{ref}`), the places of any identifier
 * (`GET /identifiers/places/{kind}/{ref}`); for each document, the place of a value (`fact`:
 * `GET /documents/{id}/places/{kind}/{ref}`, a relation's shared number), or the quotes of its
 * open fields (`review`: `GET /documents/{id}/review`, why it waits in the inbox). */
export type BeamSource = ValueSource | { kind: 'review' };

/** A source that names the places of a value of `identifier` by its reference. */
export interface ValueSource {
	kind: 'open' | 'places' | 'fact';
	identifier: IdentifierKind;
	ref: string;
}

export interface BeamState {
	/** The documents to page through, in order. */
	ids: string[];
	/** The one shown. */
	index: number;
	/** The place it was opened from ("Dokumente"): the way back from the document names it. */
	from: string;
	/** Opened from the inbox: "Dokument öffnen" opens it there, with its neighbours. */
	inbox?: boolean;
	/** Where the marked places come from; without, the pages are shown from the first. */
	source?: BeamSource;
}

/** Open the Beam on `id`, paging through `ids` (each once); `from` names the place. */
export function openBeam(
	ids: readonly string[],
	id: string,
	from: string,
	options: { inbox?: boolean; source?: BeamSource } = {}
): void {
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const unique = [...new Set(ids)];
	const index = Math.max(0, unique.indexOf(id));
	pushEntry('beam', { ids: unique, index, from, ...options });
}

/** Show the document at `index` of the open Beam, in the same history entry. */
export function beamTo(index: number): void {
	const beam = page.state.beam;
	if (!beam || index < 0 || index >= beam.ids.length) return;
	replaceEntry('beam', { ...beam, index });
}

/** Close the Beam. */
export function closeBeam(): void {
	dropEntry('beam');
}
