import { defineConfig } from 'sanity'
import { structureTool } from 'sanity/structure'
import article from './sanity/schemas/article'

// Config for the Studio mounted at /studio. Sanity handles its own auth: only
// members of this project can edit, everyone else gets a login screen.
export default defineConfig({
  name: 'merlins-minty-cards',
  title: "Merlin's Minty Cards",
  projectId: process.env.NEXT_PUBLIC_SANITY_PROJECT_ID!,
  dataset: process.env.NEXT_PUBLIC_SANITY_DATASET!,
  basePath: '/studio',
  plugins: [structureTool()],
  schema: { types: [article] },
})
