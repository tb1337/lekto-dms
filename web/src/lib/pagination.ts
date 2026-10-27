/** Which pages a pager offers: the first and the last, the current one with its neighbours. */
export const GAP = '…';
export type PageSlot = number | typeof GAP;

/**
 * The page numbers to show for `current` of `last` pages: 1 and `last` always, `current` with
 * one neighbour on each side, a gap where pages are left out ("1 … 9 10 11 … 26"); a gap of a
 * single page shows that page instead.
 */
export function pageSlots(current: number, last: number): PageSlot[] {
	if (last <= 1) return [1];
	const wanted = new Set<number>([1, last]);
	for (let page = current - 1; page <= current + 1; page++) {
		if (page >= 1 && page <= last) wanted.add(page);
	}
	// A gap of one page is that page.
	for (const page of [...wanted]) {
		if (page + 2 <= last && wanted.has(page + 2)) wanted.add(page + 1);
	}
	const pages = [...wanted].sort((a, b) => a - b);
	const slots: PageSlot[] = [];
	let previous = 0;
	for (const page of pages) {
		if (page - previous > 1) slots.push(GAP);
		slots.push(page);
		previous = page;
	}
	return slots;
}

/** How many pages `total` items make at `size` per page: at least one. */
export function pageCount(total: number, size: number): number {
	return Math.max(1, Math.ceil(total / size));
}
