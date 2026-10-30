/** The lens the documents page has open, for the search in the header ("Search in “To pay” …"),
 * with its words (what a plain link to it searches for); null on every other page. */
export const openLens = $state<{ name: string | null; query: string | null }>({
	name: null,
	query: null
});
