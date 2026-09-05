'use client'

import { BookOpen } from 'lucide-react'
import AdminDocsExplorer from '@/components/admin/docs/AdminDocsExplorer'

export default function AdminDocsPage() {
  return (
    <div className="p-6 lg:p-8">
      <header className="mb-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-mint/70">
          Admin
        </span>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-pine-100">
          <BookOpen size={18} className="text-mint" />
          Docs
        </h1>
        <p className="mt-1 text-sm text-pine-300">
          How the admin panel works, what things cost, and how the numbers on
          screen are calculated. Ask the Analyst Chat the same questions
          directly if you&rsquo;d rather not browse.
        </p>
      </header>

      <AdminDocsExplorer />
    </div>
  )
}
