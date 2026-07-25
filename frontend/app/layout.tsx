import type { Metadata } from 'next'
import { Fraunces, Inter } from 'next/font/google'
import AuthSessionProvider from '@/components/providers/SessionProvider'
import './globals.css'

const fraunces = Fraunces({
  subsets: ['latin'],
  variable: '--font-fraunces',
  display: 'swap',
})
const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  // Resolves relative OG image URLs to absolute ones, which social scrapers
  // require. Falls back to localhost in dev.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  title: {
    default: "Merlin's Minty Cards",
    template: "%s | Merlin's Minty Cards",
  },
  description: "Pokemon card inventory and collector resources from Merlin's Minty Cards.",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${inter.variable}`}>
      <body className="bg-cream text-ink font-sans antialiased">
        <AuthSessionProvider>{children}</AuthSessionProvider>
      </body>
    </html>
  )
}
