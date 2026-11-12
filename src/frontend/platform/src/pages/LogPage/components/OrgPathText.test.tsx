import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { OrgPathText } from './OrgPathText'

const path = 'Root/Sales/East/North/Team'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('keeps a path that fits in the cell without a tooltip', async () => {
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(80)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200)
  render(<OrgPathText text="Root/Sales" />)
  const cell = screen.getByText('Root/Sales')
  expect(cell).not.toHaveAttribute('tabindex')
  fireEvent.pointerEnter(cell, { pointerType: 'mouse' })
  await new Promise((resolve) => setTimeout(resolve, 200))
  expect(screen.queryByRole('tooltip')).toBeNull()
})

it('reveals the full path on hover once the cell clips it', async () => {
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(480)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(200)
  render(<OrgPathText text={path} />)
  const cell = screen.getByText(path)
  expect(cell).toHaveClass('truncate')
  expect(cell).toHaveAttribute('tabindex', '0')
  fireEvent.pointerMove(cell, { pointerType: 'mouse' })
  expect(await screen.findByRole('tooltip')).toHaveTextContent(path)
})
