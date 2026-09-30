import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import SensitivityPanel from './SensitivityPanel'

const end = (value: number, peak: number) => ({ value, peak_m3s: peak, time_to_peak_min: 60, volume_mcm: 1 })

describe('SensitivityPanel', () => {
  it('draws one bar per factor, widest first as served, with the notes', async () => {
    mockFetch({
      '/sensitivity': {
        body: {
          run_id: 'r', method: 'oat',
          base: { width_m: 500, formation_time_min: 80, level_m: 830, peak_m3s: 1000 },
          factors: [
            { factor: 'Breach formation time (min)', basis: 'models', base_value: 80, low: end(80, 1000), high: end(630, 250), swing_m3s: 750 },
            { factor: 'Reservoir level (m MSL)', basis: 'yaml', base_value: 830, low: end(740, 400), high: end(830, 1000), swing_m3s: 600 },
          ],
          notes: ['Each factor is varied alone.'],
        },
      },
    })
    renderWithQuery(<SensitivityPanel runId="r" />)
    const rows = await screen.findAllByTestId('tornado-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Breach formation time')
    expect(screen.getByText('Each factor is varied alone.')).toBeInTheDocument()
  })
})
