import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { FileStatusFilter } from './FileStatusFilter'

afterEach(cleanup)
it('keeps parsing available and applies its status code', () => {
    const apply = vi.fn()
    function Filter() {
        const [draft, setDraft] = useState<number[]>([])
        return <FileStatusFilter open onOpenChange={() => undefined} selected={[]} draft={draft}
            onDraftChange={setDraft} onApply={() => apply(draft)} onReset={() => setDraft([])} />
    }
    render(<Filter />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'parsing' }))
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(apply).toHaveBeenCalledWith([1])
})
