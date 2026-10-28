import { describe, expect, it } from 'vitest';
import { buttonVariants } from '#lib/components/ui/button/index.ts';
import { cn } from '#lib/utils.ts';

describe('class merging', () => {
	it('keeps a text colour beside a step of the type scale', () => {
		for (const step of ['nano', 'micro', 'meta', 'md', 'figure', 'title']) {
			expect(cn('text-primary-foreground', `text-${step}`)).toBe(
				`text-primary-foreground text-${step}`
			);
		}
		// Two steps are still one size: the last wins.
		expect(cn('text-sm', 'text-meta')).toBe('text-meta');
	});

	it('keeps the primary button light on petrol in every size', () => {
		for (const size of ['default', 'sm', 'xs', 'lg'] as const) {
			expect(buttonVariants({ variant: 'default', size })).toContain('text-primary-foreground');
		}
	});
});
