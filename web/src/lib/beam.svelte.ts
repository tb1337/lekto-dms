/**
 * The Beam (web/DESIGN.md, "Beam"): a sheet from the right that shows a document's pages
 * without leaving the place. Its state lives in the history entry (`page.state.beam`), ids
 * only, so a reload brings it back (`persistState`) and the back button closes it. Opening
 * pushes an entry, paging replaces it, closing goes back to the entry before (or, after a
 * reload, where this page did not push it, replaces it).
 */
import { goto } from '$app/navigation';
import { page } from '$app/state';

export interface BeamState {
	/** The documents to page through, in order. */
	ids: string[];
	/** The one shown. */
	index: number;
	/** The place it was opened from ("Dokumente"): the way back from the document names it. */
	from: string;
	/** Opened from the inbox: "Dokument öffnen" opens it there, with its neighbours. */
	inbox?: boolean;
}

// Whether the entry of the open Beam was pushed by this page (else: restored by a reload).
let pushed = false;

/** Open the Beam on `id`, paging through `ids` (each once); `from` names the place. */
export function openBeam(
	ids: readonly string[],
	id: string,
	from: string,
	options: { inbox?: boolean } = {}
): void {
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const unique = [...new Set(ids)];
	const index = Math.max(0, unique.indexOf(id));
	pushed = true;
	void goto(page.url.href, {
		shallow: true,
		state: { ...page.state, beam: { ids: unique, index, from, ...options } },
		persistState: true
	});
}

/** Show the document at `index` of the open Beam, in the same history entry. */
export function beamTo(index: number): void {
	const beam = page.state.beam;
	if (!beam || index < 0 || index >= beam.ids.length) return;
	void goto(page.url.href, {
		shallow: true,
		replace: true,
		state: { ...page.state, beam: { ...beam, index } },
		persistState: true
	});
}

/** Close the Beam: back to the entry before it, or that entry's state without it. */
export function closeBeam(): void {
	if (!page.state.beam) return;
	if (pushed) {
		pushed = false;
		history.back();
		return;
	}
	const state = { ...page.state };
	delete state.beam;
	void goto(page.url.href, { shallow: true, replace: true, state, persistState: true });
}
