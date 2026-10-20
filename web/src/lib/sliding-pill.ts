/**
 * The light pill behind the chosen entry of a bar (`TabBar`, `Segmented`), which moves over to
 * the entry chosen next instead of appearing there (Tobi, 20.10.2026). An attachment of the bar:
 * it lays the bar's `[data-pill]` under its entry with `aria-current="page"` or
 * `aria-pressed="true"`, and again when another one is chosen or the chosen one changes its size
 * (counts, fonts, bold text). The first placing is not animated: the bar sets `data-moving` on
 * the pill a frame later, and only then does its CSS move it (unless the person asks for reduced
 * motion). Without a chosen entry the pill is hidden.
 */
const CHOSEN = '[aria-current="page"], [aria-pressed="true"]';

export function slidingPill(bar: HTMLElement): () => void {
	const found = bar.querySelector<HTMLElement>(':scope > [data-pill]');
	if (!found) return () => {};
	const pill: HTMLElement = found;
	let shown: HTMLElement | null = null;
	const sizes = new ResizeObserver(() => place());

	function place() {
		const chosen = bar.querySelector<HTMLElement>(CHOSEN);
		if (chosen !== shown) {
			if (shown) sizes.unobserve(shown);
			if (chosen) sizes.observe(chosen);
			shown = chosen;
		}
		if (!chosen) {
			pill.hidden = true;
			return;
		}
		// The bar is positioned, so the entry's offsets are within it, scrolled or not.
		pill.style.width = `${chosen.offsetWidth}px`;
		pill.style.height = `${chosen.offsetHeight}px`;
		pill.style.transform = `translate(${chosen.offsetLeft}px, ${chosen.offsetTop}px)`;
		pill.hidden = false;
	}

	const changes = new MutationObserver(place);
	changes.observe(bar, {
		subtree: true,
		childList: true,
		attributes: true,
		attributeFilter: ['aria-current', 'aria-pressed']
	});
	sizes.observe(bar);
	place();
	const frame = requestAnimationFrame(() => {
		pill.dataset.moving = '';
	});
	return () => {
		cancelAnimationFrame(frame);
		changes.disconnect();
		sizes.disconnect();
	};
}
