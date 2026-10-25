/**
 * A web address the browser may be sent to: `http:` or `https:` only, resolved against `base`
 * (the page's origin). Null for anything else the API or a link could hand over (`javascript:`,
 * `data:`, garbage): the UI never navigates there.
 */
export function httpUrl(url: string, base: string): string | null {
	try {
		const parsed = new URL(url, base);
		return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
	} catch {
		return null;
	}
}
