import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  EngineBadge,
  KpiCard,
  NOT_COMPUTED,
  formatInteger,
  formatMinutes,
  formatNumber,
} from './Value'

/**
 * Engineering rule 1 in the UI: a value that was not computed renders as an
 * em dash, and never as zero. "Zero buildings flooded" and "we could not
 * fetch the building layer" are different statements about the world.
 */
describe('not computed is never zero', () => {
  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])(
    'formatNumber(%s) is an em dash',
    (value) => {
      expect(formatNumber(value as number | null)).toBe(NOT_COMPUTED)
      expect(formatNumber(value as number | null)).not.toMatch(/0/)
    },
  )

  it('formatInteger and formatMinutes follow the same rule', () => {
    expect(formatInteger(null)).toBe(NOT_COMPUTED)
    expect(formatMinutes(null)).toBe(NOT_COMPUTED)
    expect(formatMinutes(undefined)).toBe(NOT_COMPUTED)
  })

  it('a real zero is still shown as zero', () => {
    expect(formatInteger(0)).toBe('0')
    expect(formatNumber(0, 1)).toBe('0.0')
  })

  it('a null KPI renders an em dash, the words "not computed", and no unit', () => {
    render(
      <KpiCard label="Buildings affected" value={null} unit="bldg" reason="OSM layer missing" />,
    )
    expect(screen.getByText(NOT_COMPUTED)).toBeInTheDocument()
    expect(screen.getByText('not computed')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.queryByText('bldg')).not.toBeInTheDocument()
    expect(screen.getByTitle('OSM layer missing')).toBeInTheDocument()
  })

  it('a computed KPI renders its number and unit', () => {
    render(<KpiCard label="Max depth" value={12.345} unit="m" decimals={2} />)
    expect(screen.getByText('12.35')).toBeInTheDocument()
    expect(screen.getByText('m')).toBeInTheDocument()
    expect(screen.queryByText('not computed')).not.toBeInTheDocument()
  })
})

describe('engine labels are rendered verbatim', () => {
  it('shows the probed display name, not a nicer one', () => {
    const name = 'FloodGuard-SWE (Delft3D-class FV solver)'
    render(<EngineBadge displayName={name} isRealSolver />)
    expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.queryByText('Delft3D')).not.toBeInTheDocument()
  })

  it('marks a substituted engine visibly', () => {
    render(
      <EngineBadge
        displayName="FloodGuard-SPH (depth-integrated SWE-SPH)"
        isRealSolver
        substituted
      />,
    )
    expect(screen.getByText('⚠')).toBeInTheDocument()
  })
})
