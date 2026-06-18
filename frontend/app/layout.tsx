import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: {
    default: "Merlin's Minty Cards",
    template: "%s | Merlin's Minty Cards",
  },
  description: "Pokemon card inventory and collector resources from Merlin's Minty Cards.",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
