/**
 * Choosing from a `Select` in tests, whichever form it has: the native select of a phone, or
 * the list of a wider screen; and from a searchable choice (`SearchSelect`). The triggers of
 * the lists carry their value as `data-value`, their options it as `data-value` too.
 */
import { fireEvent, screen, within } from '@testing-library/svelte';
import type { UserEvent } from '@testing-library/user-event';

export interface Choice {
	value: string;
	label: string;
}

const native = (field: HTMLElement): field is HTMLSelectElement =>
	field instanceof HTMLSelectElement;

/** The value the field shows. */
export function selectedValue(field: HTMLElement): string {
	return native(field) ? field.value : (field.dataset.value ?? '');
}

type User = Pick<UserEvent, 'click' | 'selectOptions'>;

/** Open the list of `field`: a select opens on the pointer going down, a popover on a click. */
async function open(field: HTMLElement): Promise<HTMLElement> {
	await fireEvent.pointerDown(field, { button: 0, pointerType: 'mouse' });
	if (!screen.queryByRole('listbox')) await fireEvent.click(field);
	return screen.findByRole('listbox');
}

function choices(list: HTMLElement): { element: HTMLElement; choice: Choice }[] {
	return within(list)
		.getAllByRole('option')
		.map((element) => ({
			element,
			choice: { value: element.dataset.value ?? '', label: element.textContent?.trim() ?? '' }
		}));
}

/** The options of the field, in their order. */
export async function optionsOf(field: HTMLElement): Promise<Choice[]> {
	if (native(field)) {
		return [...field.options].map((option) => ({ value: option.value, label: option.text }));
	}
	const list = await open(field);
	const found = choices(list).map(({ choice }) => choice);
	await fireEvent.keyDown(list, { key: 'Escape' });
	return found;
}

/** Choose the option with `wanted` as value or label. */
export async function choose(user: User, field: HTMLElement, wanted: string): Promise<void> {
	if (native(field)) {
		await user.selectOptions(field, wanted);
		return;
	}
	const list = await open(field);
	const found = choices(list).find(
		({ choice }) => choice.value === wanted || choice.label === wanted
	);
	if (!found) throw new Error(`no option ${wanted}`);
	await user.click(found.element);
}
