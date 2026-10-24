import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { coalesced } from './coalesce.ts';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('coalesced', () => {
	it('runs once after a burst, and not at all when cancelled', () => {
		const run = vi.fn();
		const later = coalesced(run, 300);
		later();
		vi.advanceTimersByTime(200);
		later();
		later();
		vi.advanceTimersByTime(299);
		expect(run).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(run).toHaveBeenCalledOnce();
		later();
		later.cancel();
		vi.advanceTimersByTime(1000);
		expect(run).toHaveBeenCalledOnce();
	});
});
