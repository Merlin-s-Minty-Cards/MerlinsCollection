import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker runtime image doesn't
  // need the full node_modules tree.
  output: 'standalone',
  images: {
    remotePatterns: [
      // TCGdex card art (returned by the inventory backend)
      { protocol: 'https', hostname: 'assets.tcgdex.net' },
      // pokemontcg.io card art — still live in DynamoDB until the catalog is
      // reseeded over TCGdex; remove once no stored card carries these URLs.
      { protocol: 'https', hostname: 'images.pokemontcg.io' },
      // Sanity CMS article images. Scoped to our own project: allowing all of
      // cdn.sanity.io would turn /_next/image into an open image proxy that
      // anyone could run their bandwidth through.
      {
        protocol: 'https',
        hostname: 'cdn.sanity.io',
        pathname: `/images/${process.env.NEXT_PUBLIC_SANITY_PROJECT_ID}/**`,
      },
      // Add CloudFront domain here when provisioned:
      // { protocol: 'https', hostname: '<id>.cloudfront.net' }
    ],
  },
}

export default nextConfig
