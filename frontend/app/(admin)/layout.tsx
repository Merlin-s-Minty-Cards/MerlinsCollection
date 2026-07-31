import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import AdminShell from '@/components/admin/AdminShell'

/**
 * Admin layout — gates all /admin/* pages behind admin session.
 * Redirects to home if not authenticated or not an admin.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()

  if (!session || session.error) {
    redirect('/api/auth/signin?callbackUrl=/admin')
  }

  if (!session.isAdmin) {
    redirect('/')
  }

  return <AdminShell>{children}</AdminShell>
}
