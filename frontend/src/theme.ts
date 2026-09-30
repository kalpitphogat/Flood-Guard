import { useSyncExternalStore } from 'react'

/**
 * Light / dark theme. Dark is the default; the choice is remembered per browser.
 *
 * The class on <html> drives Tailwind's `dark:` variant and the theme layer in
 * index.css. index.html applies it before first paint so the page never flashes
 * light; this module keeps it in sync afterwards.
 */

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'floodguard.theme'
const listeners = new Set<() => void>()

function read(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

let current: Theme = read()

function apply(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

apply(current)

export function getTheme(): Theme {
  return current
}

export function setTheme(theme: Theme) {
  current = theme
  apply(theme)
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Private windows may refuse storage; the theme still applies for this visit.
  }
  listeners.forEach((fn) => fn())
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, getTheme)
}
