/**
 * How long something took, as Tobi wants to read it (22.10.2026): the unit right after the
 * number and never broken over two lines ("0,4s", "4,2s", "48s", "1m 3s", "2h 5m").
 */
import { formatNumber } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';

/** `seconds` as a duration: tenths below ten seconds, whole seconds below a minute, then
 * minutes and seconds, from an hour on hours and minutes. */
export function formatDuration(seconds: number): string {
	const value = Math.max(0, seconds);
	if (value < 10) {
		return m.duration_seconds({ seconds: formatNumber(value, { maximumFractionDigits: 1 }) });
	}
	const whole = Math.round(value);
	if (whole < 60) return m.duration_seconds({ seconds: formatNumber(whole) });
	if (whole < 3600) {
		return m.duration_minutes({
			minutes: String(Math.floor(whole / 60)),
			seconds: String(whole % 60)
		});
	}
	const minutes = Math.round(whole / 60);
	return m.duration_hours({
		hours: String(Math.floor(minutes / 60)),
		minutes: String(minutes % 60)
	});
}
