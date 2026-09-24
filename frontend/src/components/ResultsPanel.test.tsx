import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import { AoiPanel, ComparisonTable } from './ResultsPanel'

describe('ComparisonTable', () => {
  it('shows the note and no numbers when only one engine ran', async () => {
    mockFetch({
      '/comparison': {
        body: {
          run_id: 'r1',
          engines: ['swe_fv'],
          engine_display_names: { swe_fv: 'FloodGuard-SWE (Delft3D-class FV solver)' },
          rows: [],
          critical_success_index: null,
          extent_rmse_m: null,
          note: 'Only 1 engine produced a result. No placeholder numbers are shown.',
        },
      },
    })
    renderWithQuery(<ComparisonTable runId="r1" />)
    expect(await screen.findByText(/No placeholder numbers are shown/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders every computed cell and a dash for a missing difference', async () => {
    mockFetch({
      '/comparison': {
        body: {
          run_id: 'r1',
          engines: ['swe_fv', 'sph_swe'],
          engine_display_names: {
            swe_fv: 'FloodGuard-SWE (Delft3D-class FV solver)',
            sph_swe: 'FloodGuard-SPH (depth-integrated SWE-SPH)',
          },
          rows: [
            {
              metric: 'Maximum depth',
              unit: 'm',
              values: { swe_fv: 10, sph_swe: 9 },
              difference_pct: -10,
            },
            {
              metric: 'Earliest arrival',
              unit: 'min',
              values: { swe_fv: null, sph_swe: 3 },
              difference_pct: null,
            },
          ],
          critical_success_index: 0.8,
          extent_rmse_m: 1.2,
          note: '',
        },
      },
    })
    renderWithQuery(<ComparisonTable runId="r1" />)
    expect(await screen.findByText('-10.0%')).toBeInTheDocument()
    // The missing swe_fv arrival and the missing difference are both dashes.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })
})

describe('AoiPanel', () => {
  it('renders a bare dash, never "— km²", when the AOI is outside the model', async () => {
    mockFetch({
      '/aoi-stats': {
        body: {
          run_id: 'r1',
          upload_id: 'u1',
          aoi_name: 'district.geojson',
          aoi_area_km2: 120,
          covered_by_model_km2: 0,
          coverage_fraction: 0,
          flooded_area_km2: null,
          max_depth_m: null,
          earliest_arrival_min: null,
          reason: 'The AOI does not overlap the simulation domain.',
        },
      },
    })
    renderWithQuery(<AoiPanel runId="r1" uploadId="u1" />)
    await waitFor(() => expect(screen.getByText(/does not overlap/)).toBeInTheDocument())
    expect(screen.queryByText(/— km²/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^0(\.0+)? km²/)).not.toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })
})
