import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

/** Render inside a fresh QueryClient with retries off, so errors surface at once. */
export function renderWithQuery(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

/** Route fetch() by URL substring to canned JSON responses. First match wins. */
export function mockFetch(routes: Record<string, { status?: number; body: unknown }>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    const key = Object.keys(routes).find((k) => url.includes(k))
    if (!key) {
      return new Response(JSON.stringify({ detail: `unmocked ${url}` }), { status: 404 })
    }
    const { status = 200, body } = routes[key]
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}
