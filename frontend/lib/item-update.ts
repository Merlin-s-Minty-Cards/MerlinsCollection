/**
 * Applying an admin edit to a list the page is already showing.
 *
 * RFC 0010 T5. `CardDetailModal` used to answer a successful edit with a bare
 * `onUpdated()`, and every page it is mounted by responded by refetching its
 * whole list. That replaced the array — which re-mounts the table and throws an
 * admin who had scrolled well down back to the top — while leaving the object
 * the modal was rendering untouched, so the edited value did not appear until
 * the modal was closed and reopened. Both halves of the owner's report, one
 * cause.
 *
 * The modal now hands back the server's own copy of the item and the page
 * patches the one row. See `CardDetailModal`'s `onUpdated` for the fallback:
 * `updated` is optional, so a parent that ignores it keeps the old refetch.
 */

/**
 * The server's copy of an item, as `PUT /admin/inventory/{item_id}` returns it.
 *
 * Deliberately a loose record rather than a typed item: each page carries its
 * own row interface (`InventoryItem`, `VaultItem`, `MispricedItem`, …) and this
 * has to merge into all of them.
 *
 * **It is `_serialize_item` and nothing more.** The keys the SEARCH endpoint
 * bolts on for the triage view — `triage_reasons`, `bulk_clearable`, the joined
 * `card` — are attached by `_attach_triage_reasons` / `_attach_catalog_cards`
 * on `?triage=true` rows only, so they are absent here. Reading one off an
 * update response gets `undefined`, not an answer.
 */
export type UpdatedItem = Record<string, unknown>

/**
 * Replace one row with the server's updated copy, in place.
 *
 * **Spread, never replace.** `{ ...row, ...updated }` keeps the keys the list
 * request added and the update response does not carry (see `UpdatedItem`);
 * substituting the response wholesale would silently strip a triage row's
 * reason chips and its joined catalog card.
 *
 * Order is preserved and no other row is touched, which is the point: the array
 * identity changes but the table does not re-mount, so scroll position and sort
 * order survive an edit.
 */
export function patchRow<T extends { item_id: string }>(
  rows: T[],
  updated: UpdatedItem,
): T[] {
  const id = String(updated.item_id)
  // The cast is unavoidable: `updated` is an untyped record, so TypeScript
  // widens the spread to `T & Record<string, unknown>`. The narrowing is safe
  // because the merge only ever adds keys to a row that already satisfies `T`.
  return rows.map((row) => (row.item_id === id ? ({ ...row, ...updated } as T) : row))
}
