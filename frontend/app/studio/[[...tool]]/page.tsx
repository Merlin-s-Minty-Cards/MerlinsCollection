'use client'

import { NextStudio } from 'next-sanity/studio'
import config from '@/sanity.config'

// The Studio runs entirely in the browser — it builds its own React context and
// styled-components tree, neither of which survive Next's server module graph.
// Hence the client boundary here; page metadata lives in the sibling layout.
export default function StudioPage() {
  return <NextStudio config={config} />
}
