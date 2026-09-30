import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import { CrossSectionChart } from './Charts'

const SECTION = {
  location: 'Devprayag',
  offsets_m: [-100, 0, 100],
  bed_m: [480, 470, 480],
  water_surface_m: [null, 500, null],
  offset_from_path_m: 0,
}

describe('CrossSectionChart', () => {
  it('shows the chainage in km', async () => {
    mockFetch({ '/cross-section': { body: { ...SECTION, chainage_m: 68400 } } })
    renderWithQuery(
      <CrossSectionChart runId="r" scenario={null} location="Devprayag" onLocationChange={() => {}} />,
    )
    expect(await screen.findByText(/chainage 68\.4 km downstream/)).toBeInTheDocument()
  })

  it('shows a dash, never 0 km, when the chainage is unknown', async () => {
    mockFetch({ '/cross-section': { body: { ...SECTION, chainage_m: null } } })
    renderWithQuery(
      <CrossSectionChart runId="r" scenario={null} location="Devprayag" onLocationChange={() => {}} />,
    )
    expect(await screen.findByText(/chainage — downstream/)).toBeInTheDocument()
    expect(screen.queryByText(/0\.0 km/)).not.toBeInTheDocument()
  })
})
