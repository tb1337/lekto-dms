/**
 * Where the header has room for its search field and where only a magnifier, by width: on a
 * phone the magnifier; from md the field instead of the menu; from xl the menu takes the room
 * and the magnifier stands; from 2xl both (an admin's longer menu: from 1720 px; German names
 * are long). The
 * documents page has a field of its own exactly where the header has none: on a phone in its
 * search row (`phone`), on a desktop by the title (`title`). The classes stand here whole, so
 * that Tailwind finds them.
 */
export function searchPlaces(admin: boolean): {
	field: string;
	icon: string;
	phone: string;
	title: string;
} {
	return admin
		? {
				field: 'hidden w-64 md:flex xl:hidden min-[107.5rem]:flex min-[107.5rem]:w-80',
				icon: 'md:hidden xl:inline-flex min-[107.5rem]:hidden',
				phone: 'md:hidden',
				title: 'hidden xl:flex min-[107.5rem]:hidden'
			}
		: {
				field: 'hidden w-64 md:flex xl:hidden 2xl:flex 2xl:w-80',
				icon: 'md:hidden xl:inline-flex 2xl:hidden',
				phone: 'md:hidden',
				title: 'hidden xl:flex 2xl:hidden'
			};
}
