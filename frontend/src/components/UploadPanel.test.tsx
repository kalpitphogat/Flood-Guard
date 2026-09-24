import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockFetch, renderWithQuery } from '../test/utils'
import UploadPanel from './UploadPanel'

describe('UploadPanel', () => {
  it('lists every reason a file was refused, and selects nothing', async () => {
    mockFetch({
      '/api/uploads/dem': {
        status: 422,
        body: {
          detail: {
            message: 'the dem file was refused',
            issues: ['the raster has no coordinate reference system'],
          },
        },
      },
      '/api/uploads': { body: [] },
    })
    const onChange = vi.fn()
    renderWithQuery(
      <UploadPanel selection={{ dem: null, hydrograph: null, aoi: null }} onChange={onChange} />,
    )
    fireEvent.click(screen.getByText('Show'))
    const input = screen.getByLabelText('Upload DEM (GeoTIFF)')
    fireEvent.change(input, { target: { files: [new File(['x'], 'bad.tif')] } })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'no coordinate reference system',
    )
    expect(onChange).not.toHaveBeenCalled()
  })
})
