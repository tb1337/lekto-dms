/** The lens the documents page has open, for the search in the header ("Search in “To pay” …");
 * null on every other page. */
export const openLens = $state<{ name: string | null }>({ name: null });
