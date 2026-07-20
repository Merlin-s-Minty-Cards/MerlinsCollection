import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker runtime image doesn't
  // need the full node_modules tree.
  output: 'standalone',
  images: {
    remotePatterns: [
      // pokemontcg.io card art (returned by the inventory backend)
      { protocol: 'https', hostname: 'images.pokemontcg.io' },
      // Add CloudFront domain here when provisioned:
      // { protocol: 'https', hostname: '<id>.cloudfront.net' }
    ],
  },
}

export default nextConfig
