/**
 * `steady-weight` (web/DESIGN.md, "Steady layout") for a label given as markup, not as a string
 * (`SteadyText` takes one): its text, copied into `data-text` and kept there as it changes.
 */
import type { Attachment } from 'svelte/attachments';

export const steadyText: Attachment<HTMLElement> = (element) => {
	const copy = () => {
		element.dataset.text = element.textContent ?? '';
	};
	copy();
	const observer = new MutationObserver(copy);
	observer.observe(element, { characterData: true, childList: true, subtree: true });
	return () => observer.disconnect();
};
