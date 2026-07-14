export { metadata, viewport } from 'next-sanity/studio'

/**
 * The Studio owns the full viewport and ships its own styles, so it opts out of
 * the site chrome the public pages get.
 */
export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return children
}
