/** The options of the choices in a rule's rows. */
import { m } from '#lib/paraglide/messages.js';

export interface Option {
	value: string;
	label: string;
}

/** Contacts, types or fields as options: by id, named. */
export function namedOptions(list: readonly { id: string; name: string }[]): Option[] {
	return list.map((entry) => ({ value: entry.id, label: entry.name }));
}

/**
 * The options of a choice: "Choose…" first, then `options`, and after them the current
 * `value` when it is none of them (deleted since, or not the caller's to pick), labelled
 * `unknown`, so that it is kept and shown rather than silently replaced.
 */
export function withChoice(
	options: readonly Option[],
	value: string,
	unknown: string = m.rule_unknown()
): Option[] {
	const known = value === '' || options.some((option) => option.value === value);
	return [
		{ value: '', label: m.rule_choose() },
		...options,
		...(known ? [] : [{ value, label: unknown }])
	];
}
