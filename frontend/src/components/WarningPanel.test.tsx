import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import WarningPanel from './WarningPanel'

const base = {
  run_id: 'r1',
  scenario: 'Tehri',
  issued_utc: '2026-09-25T00:00:00Z',
  counts: { RED: 1, ORANGE: 0, YELLOW: 0, NONE: 0, NOT_ASSESSED: 1 },
  population_red_orange: null,
  convention: 'Alert levels are a FloodGuard convention pending the district EAP.',
  safe_ground_method: 'Straight-line distance, not a route.',
  disclaimer_en: 'MODEL SCENARIO — NOT AN OFFICIAL WARNING.',
  disclaimer_hi: 'आधिकारिक चेतावनी नहीं।',
  note: '',
  sms: [],
  sms_hi: [],
}

const town = {
  lon: 78.6,
  lat: 30.1,
  action_en: 'Evacuate now',
  action_hi: 'तुरंत',
  arrival_min: 30,
  max_depth_m: 8,
  max_velocity_ms: 4,
  hazard_class: 'H6',
  population: 2152,
  reasons: [],
}

describe('WarningPanel', () => {
  it('shows levels and the disclaimer, and a dash — not 0 km — when no safe ground exists', async () => {
    mockFetch({
      '/warning': {
        body: {
          ...base,
          towns: [
            {
              ...town,
              name: 'Devprayag',
              level: 'RED',
              safe_ground: null,
              safe_ground_reason: 'no cell inside the modelled corridor stands clear of the flood',
            },
            {
              ...town,
              name: 'Haridwar',
              level: 'NOT_ASSESSED',
              arrival_min: null,
              max_depth_m: null,
              safe_ground: null,
              safe_ground_reason: '',
            },
          ],
        },
      },
    })
    renderWithQuery(<WarningPanel runId="r1" />)
    expect(await screen.findByText('Devprayag')).toBeInTheDocument()
    expect(screen.getByText('RED')).toBeInTheDocument()
    expect(screen.getByText('N/A')).toBeInTheDocument()
    expect(screen.getByText(/NOT AN OFFICIAL WARNING/)).toBeInTheDocument()
    expect(screen.getByText(/stands clear of the flood/)).toBeInTheDocument()
    expect(screen.queryByText(/0\.0 km/)).not.toBeInTheDocument()
    expect(screen.getByText('CAP 1.2 alert (.xml)')).toHaveAttribute(
      'href',
      '/api/results/r1/warning/cap.xml',
    )
  })
})
