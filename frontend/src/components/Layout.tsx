import { NavLink } from 'react-router-dom'

import { setTheme, useTheme } from '../theme'

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/simulation', label: 'Simulation' },
  { to: '/monitoring', label: 'Real-time Monitoring' },
  { to: '/about', label: 'About' },
]

function WaveLogo() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
      <circle cx="17" cy="17" r="16" fill="#1c4b80" />
      <path
        d="M4 20c3.2 0 3.2-3 6.5-3s3.3 3 6.5 3 3.2-3 6.5-3 3.3 3 6.5 3"
        fill="none"
        stroke="#9ed8f5"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M4 25c3.2 0 3.2-3 6.5-3s3.3 3 6.5 3 3.2-3 6.5-3 3.3 3 6.5 3"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  )
}

function ThemeToggle() {
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="flex items-center gap-1.5 rounded px-2 py-1.5 text-[11px] text-sky-100 hover:bg-white/10"
    >
      {theme === 'dark' ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-col">
      <header className="bg-navy text-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-2.5">
          <WaveLogo />
          <div className="leading-tight">
            <div className="text-lg font-semibold">FloodGuard India</div>
            <div className="text-[11px] text-sky-200">
              Dam Break &amp; Flash Flood Simulation for a Safer Tomorrow
            </div>
          </div>

          <nav className="ml-6 flex gap-1 text-sm">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded px-3 py-1.5 transition-colors ${
                    isActive ? 'bg-white/15 font-medium' : 'text-sky-100 hover:bg-white/10'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-4">
            <span className="hidden text-[11px] text-sky-200 lg:inline">
              Data Driven | Resilient Communities | Safer India
            </span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="bg-navy text-[11px] text-sky-200">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-4 py-2.5">
          <span>Indian Rivers. Safer Communities.</span>
          <span>Built for a Resilient India | HADR | v1.0.0 🇮🇳</span>
        </div>
      </footer>
    </div>
  )
}
