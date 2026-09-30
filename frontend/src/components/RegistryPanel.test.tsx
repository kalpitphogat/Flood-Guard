import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import RegistryPanel from './RegistryPanel'

describe('RegistryPanel', () => {
  it('shows each tier with the reason behind it', async () => {
    mockFetch({
      '/api/registry': {
        body: {
          note: 'computed',
          sites: [{
            scenario_id: 'h', name: 'H', dam: 'HIRAKUD', river: 'Mahanadi', tier: 'presets ready',
            tier_reason: 'all 3 stored; terrain is not on this machine', towns: 3,
            population_raster: false, osm_layers: [],
            resolutions: { '120': { terrain: { ok: false, reason: 'no DEM' }, presets_defined: 3, presets_stored: 3 } },
          }],
        },
      },
    })
    renderWithQuery(<RegistryPanel />)
    expect(await screen.findByTestId('tier')).toHaveTextContent('presets ready')
    expect(screen.getByText(/terrain is not on this machine/)).toBeInTheDocument()
    expect(screen.getByText(/3\/3 presets · no terrain/)).toBeInTheDocument()
  })
})
