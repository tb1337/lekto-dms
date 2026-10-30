/**
 * The way back after a jump (web/DESIGN.md, "Navigation between list and detail"): a place that
 * sends a person to a document (the Beam, a dialog) puts its name into the new history entry
 * (`page.state.from`); the document's `BackLink` names it and goes back in the history, to the
 * place as it was, with its dialog and Beam open. Over several jumps it goes back one step at a
 * time, as the back button does.
 */
import { goto } from '$app/navigation';
import { page } from '$app/state';
import { BASE } from '#lib/base.ts';
import { returnTo } from '#lib/return-to.svelte.ts';

/** Go to `href`, so that its way back leads here, named `label`. */
export function jumpTo(href: string, label: string): Promise<void> {
	return goto(href, { state: { from: { label } }, persistState: true });
}

/** Leave a document (it was deleted or handed over): back where a jump came from, else to the
 * inbox or the document list as it was left. */
export async function leaveDocument(inbox: boolean): Promise<void> {
	if (page.state.from) history.back();
	else await (inbox ? goto(`${BASE}/inbox`) : returnTo.goDocuments());
}
