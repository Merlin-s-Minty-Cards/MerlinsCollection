import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      // pokemontcg.io card art (returned by the inventory backend)
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
