import { describe, expect, it } from 'vitest';
import { PagedList, Pager } from './paging.svelte.ts';

const pages: Record<string, { items: number[]; next: string | null }> = {
	start: { items: [1, 2], next: 'two' },
	two: { items: [3], next: null }
};

function list(fail = false) {
	return new PagedList<number>(async (after) => {
		if (fail) throw new Error('boom');
		return pages[(after as string | null) ?? 'start'];
	});
}

describe('PagedList', () => {
	it('loads page by page', async () => {
		const items = list();
		await items.reload();
		expect(items.items).toEqual([1, 2]);
		expect(items.hasMore).toBe(true);
		await items.more();
		expect(items.items).toEqual([1, 2, 3]);
		expect(items.hasMore).toBe(false);
	});

	it('knows when it is empty', async () => {
		const items = new PagedList<number>(async () => ({ items: [], next: null }));
		expect(items.empty).toBe(false);
		await items.reload();
		expect(items.empty).toBe(true);
	});

	it('keeps the error', async () => {
		const items = list(true);
		await items.reload();
		expect(items.error).toBeInstanceOf(Error);
		expect(items.empty).toBe(false);
	});

	it('refreshes the pages shown without emptying the list', async () => {
		const items = list();
		await items.reload();
		await items.more();
		await items.refresh();
		expect(items.items).toEqual([1, 2, 3]);
	});

	it('starts over on reload', async () => {
		const items = list();
		await items.reload();
		await items.more();
		await items.reload();
		expect(items.items).toEqual([1, 2]);
	});

	it('is not stuck loading when a refresh overtakes a page in flight', async () => {
		let release: () => void = () => {};
		let hold = false;
		const items = new PagedList<number>(async (after) => {
			if (hold && after === 'two') await new Promise<void>((resolve) => (release = resolve));
			return pages[(after as string | null) ?? 'start'];
		});
		await items.reload();
		hold = true;
		const more = items.more();
		hold = false;
		await items.refresh();
		release();
		await more;
		expect(items.loading).toBe(false);
		expect(items.items).toEqual([1, 2]);
		await items.more();
		expect(items.items).toEqual([1, 2, 3]);
	});

	it('keeps the list when a refresh fails', async () => {
		let fail = false;
		const items = new PagedList<number>(async () => {
			if (fail) throw new Error('boom');
			return pages.start;
		});
		await items.reload();
		fail = true;
		await items.refresh();
		expect(items.error).toBeNull();
		expect(items.items).toEqual([1, 2]);
	});

	it('takes the total only from a page it keeps', async () => {
		let release: (() => void) | undefined;
		const paged = new PagedList<number>(async (after) => {
			if (after === null && release === undefined) {
				await new Promise<void>((resolve) => (release = resolve));
				return { items: [1], next: null, total: 1000 };
			}
			return { items: [2, 3], next: null, total: 2 };
		});
		const slow = paged.reload(); // the first answer is late ...
		await paged.reload(); // ... and this one wins
		expect(paged.total).toBe(2);
		release?.();
		await slow;
		expect(paged.total).toBe(2);
		expect(paged.items).toEqual([2, 3]);
	});
});

describe('Pager', () => {
	function pager() {
		const asked: [number, number][] = [];
		const items = Array.from({ length: 130 }, (_, index) => index);
		const paged = new Pager<number>(async (offset, limit) => {
			asked.push([offset, limit]);
			return { items: items.slice(offset, offset + limit), total: items.length };
		}, 50);
		return { paged, asked };
	}

	it('keeps the first item in view when the page size changes', async () => {
		const { paged, asked } = pager();
		await paged.go(2); // items 50 to 99
		await paged.resize(25);
		expect([paged.page, paged.size, paged.pages]).toEqual([3, 25, 6]);
		expect(paged.items[0]).toBe(50);
		await paged.go(4); // items 75 to 99
		await paged.resize(100);
		expect([paged.page, paged.pages]).toEqual([1, 2]);
		expect(asked.at(-1)).toEqual([0, 100]);
	});

	it('asks nothing for the size it has', async () => {
		const { paged, asked } = pager();
		await paged.go(1);
		await paged.resize(50);
		expect(asked).toEqual([[0, 50]]);
	});
});
