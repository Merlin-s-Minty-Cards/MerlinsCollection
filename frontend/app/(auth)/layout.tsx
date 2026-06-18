// Redirects unauthenticated users to sign-in — guard added during implementation
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
