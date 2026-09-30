import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import GaugesPanel from './GaugesPanel'

const point = (over: object) => ({
  kind: 'channel', in_domain: true, max_depth_m: 20, arrival_min: 264, series_m: [0, 5, 20],
  rising_at_end: false, near_domain_edge: false, hazard_label: 'H6', ...over,
})

const BODY = {
  run_id: 'r', times_min: [0, 5, 10], frame_interval_min: 5, notes: ['From stored frames.'],
  gauges: [
    { name: 'Rishikesh', population: 1, chainage_km: 104.9, town_to_channel_km: 2.3,
      town: point({ kind: 'town', max_depth_m: 0, series_m: [0, 0, 0] }),
      channel: point({ rising_at_end: true }) },
    { name: 'Haridwar', population: 1, chainage_km: 120.1, town_to_channel_km: null,
      town: point({ kind: 'town', in_domain: false, max_depth_m: null, series_m: null }),
      channel: null },
  ],
}

describe('GaugesPanel', () => {
  it('separates the river from the town point and says so', async () => {
    mockFetch({ '/gauges': { body: BODY } })
    renderWithQuery(<GaugesPanel runId="r" />)
    expect((await screen.findAllByText('Rishikesh')).length).toBeGreaterThan(0)
    expect(screen.getByText('dry')).toBeInTheDocument() // town point never wet
    expect(screen.getByText(/4 h 24|264/)).toBeInTheDocument() // river arrival shown
    expect(screen.getByTestId('gauge-flags')).toHaveTextContent('still rising when the run ends')
    fireEvent.click(screen.getAllByText('Haridwar')[0])
    expect(screen.getAllByText('—').length).toBeGreaterThan(0) // outside the domain: a dash, never 0
  })
})
