import type { NextAuthConfig } from 'next-auth'

// Cognito provider and callbacks added via TDD
export const authOptions = {
  providers: [],
  callbacks: {},
} satisfies NextAuthConfig
