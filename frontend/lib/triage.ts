/**
 * Triage — the shared vocabulary for "this card might be wrong".
 * docs/plans/rfc-0008/t11-triage-tab.md
 *
 * Mirrors `backend/src/merlins_collection/services/triage.py`. The reason keys
 * and the union rule are declared there and restated here only because the two
 * runtimes cannot share a module — if they drift, the list and the sidebar
 * badge disagree about what needs fixing.
 */

/** The wire shape of an inventory row as the admin surfaces receive it. */
export interface TriageItem {
  item_id: string
  kind?: string
  card_id?: string | null
  language?: string | null
  display_name?: string | null
  product_name?: string | null
  description?: string | null
  display_name_override?: string | null
  needs_review?: boolean
  review_reason?: string | null
  lineage_id?: string | null
  predecessor_item_id?: string | null
  card?: { card_id?: string; name?: string; set_name?: string; number?: string } | null
  // The admin search returns EVERY field on the item; only the ones triage
  // reasons up there are named. The index signature keeps this assignable to
  // `Record<string, unknown>`, which DataTable and CardDetailModal both require
  // (same pattern as `PrepQueueItem` in the Prep Queue page).
  [key: string]: unknown
}

export type TriageReason = 'flagged' | 'missing_card_id' | 'missing_english_name'

/** Human labels for the derived reasons. `flagged` renders its stored note instead. */
export const REASON_LABELS: Record<TriageReason, string> = {
  flagged: 'Flagged for review',
  missing_card_id: 'No catalog link',
  missing_english_name: 'Needs English name',
}

export const REASON_FILTER_OPTIONS: { value: '' | TriageReason; label: string }[] = [
  { value: '', label: 'All reasons' },
  { value: 'flagged', label: REASON_LABELS.flagged },
  { value: 'missing_card_id', label: REASON_LABELS.missing_card_id },
  { value: 'missing_english_name', label: REASON_LABELS.missing_english_name },
]

/** Only raw and graded items link to a catalog card; sealed and bulk never do. */
function isCardLinkable(item: TriageItem): boolean {
  return item.kind === 'raw' || item.kind === 'graded'
}

/**
 * Every reason this item is in the queue — one row, several chips.
 *
 * Parallel per-reason queues would list the same card repeatedly and get it
 * "fixed" twice, which is why this returns a list rather than a single reason.
 */
export function reasonsFor(item: TriageItem): TriageReason[] {
  const reasons: TriageReason[] = []
  if (item.needs_review) reasons.push('flagged')
  if (isCardLinkable(item) && !item.card_id) reasons.push('missing_card_id')
  if (item.language && item.language !== 'EN' && !item.display_name_override) {
    reasons.push('missing_english_name')
  }
  return reasons
}

/**
 * What the CUSTOMER sees, resolved through T10's precedence:
 * `display_name_override -> card.name -> display_name -> card_id -> item_id`.
 *
 * The admin has to see this and not the raw stored name, or they are editing
 * blind against the one field that actually outranks theirs.
 */
export function effectiveName(item: TriageItem): string {
  return (
    item.display_name_override?.trim() ||
    item.card?.name ||
    item.display_name ||
    item.product_name ||
    item.description ||
    item.card_id ||
    item.item_id
  )
}

/**
 * The body the note form sends. `null`, never `''` — the model normalizes blank
 * to None anyway, but an empty string on the wire is a value nobody chose.
 */
export function sendToTriageBody(note?: string | null) {
  const trimmed = note?.trim()
  return { needs_review: true, review_reason: trimmed ? trimmed : null }
}

/**
 * The row-level quick action's body. Deliberately does NOT touch
 * `review_reason`: this is the mid-workflow "that one is wrong" gesture with no
 * note attached, and sending `review_reason: null` here would wipe a reason an
 * earlier pass had recorded.
 */
export function quickFlagBody() {
  return { needs_review: true }
}

/** The body that clears an item. The server stamps `reviewed_at` itself. */
export function clearTriageBody() {
  return { needs_review: false, review_reason: null }
}
