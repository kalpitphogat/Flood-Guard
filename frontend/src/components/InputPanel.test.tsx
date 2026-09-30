import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import type { PresetCatalog, PresetEntry } from '../types/api'
import InputPanel from './InputPanel'

function entry(level: string, level_m: number, available: boolean, type = 'complete_dam_break'): PresetEntry {
  const key = `tehri_bhagirathi__${type}__${level}`
  return {
    key,
    scenario_id: 'tehri_bhagirathi',
    scenario_type: type,
    type_label: type === 'complete_dam_break' ? 'Complete dam break' : 'Overtopping failure',
    level,
    level_label: level.toUpperCase(),
    level_m,
    modelled: type === 'complete_dam_break',
    available,
    reason: available ? null : type === 'complete_dam_break' ? 'Not precomputed yet.' : 'Not modelled distinctly yet.',
    run_id: `lib_${key}`,
    completed_utc: available ? '2026-09-30T05:00:00Z' : null,
    wall_seconds: available ? 210 : null,
    resolution_m: 120,
  }
}

const CATALOG: PresetCatalog = {
  resolution_m: 120,
  resolutions: [120, 60],
  engines: ['swe_fv'],
  dams: [
    {
      scenario_id: 'tehri_bhagirathi',
      name: 'Tehri Hpp',
      duration_hours: 6,
      levels: [
        { level: 'frl', label: 'Full reservoir level (FRL)', level_m: 830 },
        { level: 'mid', label: 'Midway between FRL and MDDL', level_m: 785 },
        { level: 'mddl', label: 'Minimum drawdown level (MDDL)', level_m: 740 },
      ],
    },
  ],
  failure_types: { complete_dam_break: 'Complete dam break', overtopping: 'Overtopping failure' },
  presets: [
    entry('frl', 830, true),
    entry('mid', 785, false),
    entry('mddl', 740, true),
    entry('frl', 830, false, 'overtopping'),
    entry('mid', 785, false, 'overtopping'),
    entry('mddl', 740, false, 'overtopping'),
  ],
  quick: { resolution_m: 200, duration_hours: 1, engines: ['swe_fv'], label: 'Quick estimate — 200 m, 1 h simulated' },
}

function renderPanel(onRun = vi.fn()) {
  mockFetch({
    '/api/presets': { body: CATALOG },
    '/api/scenarios/validate': { status: 422, body: { detail: 'not needed here' } },
    '/api/scenarios': { body: [] },
    '/api/rivers': { body: [] },
    '/api/dams': { body: [] },
  })
  renderWithQuery(
    <InputPanel
      onRun={onRun}
      running={false}
      onReset={() => {}}
      uploads={{ dem: null, hydrograph: null, aoi: null }}
      onUploadsChange={() => {}}
    />,
  )
  return onRun
}

describe('InputPanel preset mode', () => {
  it('opens on the preset dropdowns and disables what is not precomputed', async () => {
    renderPanel()
    const level = await screen.findByLabelText('Reservoir level')
    const opts = within(level).getAllByRole('option') as HTMLOptionElement[]
    expect(opts.map((o) => o.disabled)).toEqual([false, true, false])
    expect(opts[1].textContent).toContain('not precomputed yet')
    expect(opts[0].textContent).toContain('830.00 m')

    const type = screen.getByLabelText('Failure type')
    const overtop = within(type).getByRole('option', { name: /Overtopping/ }) as HTMLOptionElement
    expect(overtop.disabled).toBe(true)
    // No engine picker and no free-form resolution field in preset mode: the
    // only grid choice is the precomputed-resolution dropdown.
    expect(screen.queryByText(/Grid resolution is fixed/)).toBeNull()
    expect(screen.queryByText(/Quick estimates run/)).toBeNull()
  })

  it('offers the finer grid only where it has been precomputed', async () => {
    renderPanel()
    const res = await screen.findByLabelText('Grid resolution')
    const opts = within(res).getAllByRole('option') as HTMLOptionElement[]
    expect(opts.map((o) => o.disabled)).toEqual([false, true])
    expect(opts[1].textContent).toContain('not precomputed yet')
  })

  it('submits only the scenario and the preset key', async () => {
    const onRun = renderPanel()
    fireEvent.change(await screen.findByLabelText('Reservoir level'), { target: { value: 'mddl' } })
    fireEvent.click(screen.getByRole('button', { name: 'Show precomputed result' }))
    expect(onRun).toHaveBeenCalledWith({
      scenario_id: 'tehri_bhagirathi',
      preset_key: 'tehri_bhagirathi__complete_dam_break__mddl',
    })
  })

  it('custom mode sends a quick estimate with the single engine', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: 'Custom — quick estimate' }))
    expect(await screen.findByText(/Runs live at 200 m for 1 simulated hour/)).toBeInTheDocument()
    expect(screen.getByText(/FloodGuard-SWE/)).toBeInTheDocument()
  })
})

describe('InputPanel partial breach', () => {
  it('asks for a depth fraction, labelled as the user assumption, instead of a depth', async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole('tab', { name: 'Custom — quick estimate' }))
    expect(screen.getByText('Breach Depth')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Scenario Type'), { target: { value: 'partial_breach' } })
    expect(screen.getByText('Breach Depth Fraction')).toBeInTheDocument()
    expect(screen.queryByText('Breach Depth')).toBeNull()
    expect(screen.getByTestId('partial-assumption')).toHaveTextContent(/Assumption/)
  })
})
