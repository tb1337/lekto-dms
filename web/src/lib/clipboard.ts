import { toast } from 'svelte-sonner';
import { m } from '#lib/paraglide/messages.js';

/** Put `text` on the clipboard; false where the page may not (no secure context, denied). */
export async function writeClipboard(text: string): Promise<boolean> {
	try {
		await navigator.clipboard.writeText(text);
		return true;
	} catch {
		return false;
	}
}

/** Copy `text` and say so in a toast; a failure says the text stays selectable. */
export async function copyText(text: string): Promise<void> {
	if (await writeClipboard(text)) toast.success(m.content_copied());
	else toast.error(m.copy_failed());
}
