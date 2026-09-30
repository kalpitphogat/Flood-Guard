import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ResultSummary } from '../types/api'
import RunModeBadge, { runModeLabel } from './RunModeBadge'

const base = { resolution_m: 120, duration_hours: 6, completed_utc: '2026-09-30T05:00:00Z' }

describe('RunModeBadge', () => {
  it('labels a precomputed run with its date, never as computed now', () => {
    expect(runModeLabel({ ...base, run_mode: 'precomputed' })).toBe(
      'Precomputed on 2026-09-30 · 120 m · 6 h simulated',
    )
  })

  it('labels a quick estimate with its coarse settings', () => {
    render(
      <RunModeBadge
        summary={{ ...base, resolution_m: 200, duration_hours: 1, run_mode: 'quick_estimate' } as ResultSummary}
      />,
    )
    expect(screen.getByTestId('run-mode-badge')).toHaveTextContent(
      'Quick estimate · 200 m · 1 h simulated',
    )
  })

  it('shows an em dash for an unknown resolution, never 0', () => {
    expect(runModeLabel({ ...base, resolution_m: null, duration_hours: null, run_mode: 'full' })).toBe(
      'Full run · — m',
    )
  })
})
