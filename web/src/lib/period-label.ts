import { periodOf, type Filters } from '#lib/filters.ts';
import { formatDate } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';

/** The period of the filters in words: `2026`, `September 2026`, `from …`, `… to …`; null for none. */
export function periodLabel(filters: Pick<Filters, 'dateFrom' | 'dateTo'>): string | null {
	const period = periodOf(filters);
	if (period === null) return null;
	if (period.kind === 'year') return String(period.year);
	if (period.kind === 'month') {
		return formatDate(new Date(`${period.month}-01T00:00:00`), { month: 'long', year: 'numeric' });
	}
	const day = (value: string) => formatDate(new Date(`${value}T00:00:00`), { dateStyle: 'medium' });
	if (period.from && period.to)
		return m.period_span({ from: day(period.from), to: day(period.to) });
	return period.from
		? m.period_from({ date: day(period.from) })
		: m.period_to({ date: day(period.to ?? '') });
}
