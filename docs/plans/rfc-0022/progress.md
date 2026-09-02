# RFC 0022 — Universal Admin Inline Editing & Send to Vault: PROGRESS

**Read this first.** State of the world for anyone picking up a task.

**This file is the tracked progress file — not `claude-progress.md`.**

**Last updated:** 2026-09-02 (planning only — **no task started**)
**Branch:** `feat/round9-rfcs-0021-0025`
**RFC:** [`../../rfcs/0022-universal-inline-editing.md`](../../rfcs/0022-universal-inline-editing.md)
**Task index:** [`README.md`](README.md)
**Round guide:** [`../round9/README.md`](../round9/README.md)

## Status

| Task | State |
|---|---|
| T1 Generalize `InlineEditCell` | NOT STARTED |
| T2 `EditSpec` on `Column<T>` | NOT STARTED |
| T3 Undo toast | NOT STARTED |
| T4a Adoption: six inventory pages | NOT STARTED |
| T4b Adoption: shows/cosigners/slabs/analytics | NOT STARTED |
| T5 Registries + totality tests | NOT STARTED |
| T6 `PATCH /admin/locations/{value}` | NOT STARTED |
| T7 Send to Vault | NOT STARTED |
| T8 Docs + verification | NOT STARTED |

## Next: T1

T6 and T7 are independent of everything and are the right pick for a short
session.

**RFC 0023 depends on this RFC.** Its language and finish overrides are edit
surfaces; doing 0023 first means building four bespoke forms that T4a would then
replace.

## Facts established during planning (do not re-derive these)

- **`PUT /admin/inventory/{item_id}` already does everything the backend needs.**
  It is a partial update; it validates the merged row through
  `InventoryItemAdapter`; it validates a changed `card_id` against the catalog; it
  applies the review and `no_catalog_match` transitions; and it writes a
  `type: "edit"` timeline event whose `changed_fields` are diffed from the
  **validated** before/after dumps, not the raw body — so a typo'd key or a
  re-typed-but-equal literal does not record a spurious change, and a rejected
  update writes no audit event at all.
- **`PUT /admin/shows/{show_id}` and `PATCH /admin/cosigners/{consignor_id}` are
  the same partial-update shape.** No new endpoints for those pages either.
- **`/admin/locations` has GET, POST and DELETE only.** No update route exists.
  That is the one new endpoint in this RFC.
- **Twelve surfaces render a `DataTable`:** analytics, cosigners, inventory,
  locations, market, outgoing, show-prep, shows, triage, unmatched, vault, plus
  `SlabList` and `TransactionGroups` (which replaces DataTable, and is out of
  scope — see RFC 0024).
- **`InlineEditCell` already exists** and is used by exactly two pages
  (`/admin/outgoing`, `/admin/show-prep`). It supports `'number' | 'url' | 'money'`.
- **Three surfaces do not return the entity they appear to:** `/admin/vault`
  returns computed `VaultItem`s; the analytics Shows tab joins a
  `ShowAnalyticsSnapshot`; `SlabList` renders `_slab_row()` dicts with `grade` and
  `cost_basis` **stringified**.

## Decisions made autonomously (with the rejected alternative)

- **Undo toast instead of confirmation dialogs.** The owner explicitly declined
  confirms; a mis-click on `status` or `cost_basis` still needs a cheap way back.
  Rejected: no protection at all (the owner's literal answer), and per-edit
  confirms (which defeat the feature).
- **`select` commits on change, not on blur.** Rejected blur-commit: waiting for a
  blur after picking from a dropdown is the most confusing variant of this
  pattern.
- **`PATCH /admin/locations/{value}` accepts `label` only.** Rejected accepting
  `value`: it is the join key on every item and there is no migrate path.
- **Column registries get extracted where they are inline.** Rejected leaving them
  inline: a totality test is impossible without a registry, and the exclusion list
  rots into folklore without one.
- **Transaction rows are out of scope here.** A transaction edit has a
  `cost_basis` side effect and needs a dialog, not a cell. It is RFC 0024's job.

## Owner gates on this RFC

None. Everything here is reversible and inside the owner's stated scope.
