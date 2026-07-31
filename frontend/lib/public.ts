// Typed client for the FastAPI backend's UNAUTHENTICATED /public endpoints.
// The BACKEND owns this contract (backend/src/merlins_collection/routers/public.py):
//   GET /public/shows          → { upcoming: PublicShow[], past: PublicShow[] }
//   GET /public/featured-cards → { cards: FeaturedCard[] }
// These are consumed server-side by Next.js (ISR), so each fetch opts into a
// 300s revalidate window that mirrors the backend's in-process TTL cache — new
// shows / featured cards appear without a redeploy. `date` arrives as a JSON
// string ("YYYY-MM-DD"); parse it with showBadge/formatShowDate (no Date(), which
// would treat it as UTC midnight and drift a day in a US timezone).
import { apiFetch } from './api'

/** A show as the public site sees it — safe fields only. */
export interface PublicShow {
  name: string
  /** ISO date string, e.g. "2026-08-14". */
  date: string
  venue: string | null
  city: string | null
}

export interface PublicShowsResponse {
  upcoming: PublicShow[]
  past: PublicShow[]
}

/** A featured homepage card — display name + image URL only. */
export interface FeaturedCard {
  name: string
  image_url: string
}

export interface FeaturedCardsResponse {
  cards: FeaturedCard[]
}

// Regenerate the rendered page (and re-hit the backend) at most every 5 minutes.
const REVALIDATE_SECONDS = 300

/** Fetch the public show list, split into upcoming/past by the backend. */
export async function getPublicShows(): Promise<PublicShowsResponse> {
  return apiFetch<PublicShowsResponse>('/public/shows', {
    next: { revalidate: REVALIDATE_SECONDS },
  })
}

/** Fetch the top available cards (with catalog images) for the homepage. */
export async function getFeaturedCards(): Promise<FeaturedCardsResponse> {
  return apiFetch<FeaturedCardsResponse>('/public/featured-cards', {
    next: { revalidate: REVALIDATE_SECONDS },
  })
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const

/** Parse an ISO date's parts directly (no timezone drift); null if malformed. */
function isoParts(iso: string): { year: number; month: number; day: number } | null {
  const parts = (iso ?? '').split('-').map((part) => Number.parseInt(part, 10))
  const [year, month, day] = parts
  if (parts.length < 3 || [year, month, day].some((n) => Number.isNaN(n))) return null
  return { year, month, day }
}

/** Calendar-badge month (uppercase, e.g. "AUG") + zero-padded day ("14"). */
export function showBadge(iso: string): { month: string; day: string } {
  const parts = isoParts(iso)
  if (!parts) return { month: '', day: '' }
  return {
    month: (MONTHS[parts.month - 1] ?? '').toUpperCase(),
    day: String(parts.day).padStart(2, '0'),
  }
}

/** Human-readable single-date label, e.g. "Aug 14, 2026" (empty if malformed). */
export function formatShowDate(iso: string): string {
  const parts = isoParts(iso)
  if (!parts) return ''
  return `${MONTHS[parts.month - 1] ?? ''} ${parts.day}, ${parts.year}`
}

// next/image only renders images from hosts allowlisted in next.config.ts. Mirror
// that allowlist here so a bad catalog URL (non-allowlisted host, non-https, or
// malformed) is dropped BEFORE it reaches next/image and throws during SSR —
// belt-and-suspenders with the backend's own host filter.
const ALLOWED_IMAGE_HOSTS = new Set(['assets.tcgdex.net', 'images.pokemontcg.io'])

/** True only for an https URL on an allowlisted image host. */
export function isSafeImageUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' && ALLOWED_IMAGE_HOSTS.has(parsed.hostname)
  } catch {
    return false
  }
}
