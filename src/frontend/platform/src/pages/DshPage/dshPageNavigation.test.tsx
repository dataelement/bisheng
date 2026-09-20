import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { userContext } from '@/contexts/userContext'
import DshPage from '.'
import { resolveDshSection } from './sections'

vi.mock('@/hooks/useDshBrowserConfig', () => ({
    useDshBrowserConfig: () => ({
        config: {
            management_enabled: true,
            enabled: true,
            download_url: null,
            launch_url: 'dsh-desktop://login',
        },
        failed: false,
    }),
}))

vi.mock('@/pages/SystemPage/dsh', () => ({
    DshManagement: ({ section }: { section: string }) => (
        <div data-testid="dsh-section">{section}</div>
    ),
}))

vi.mock('@/pages/BuildPage/dsh/PluginMarketPage', () => ({
    PluginMarketPage: () => <div data-testid="plugin-market">plugin market</div>,
}))

function LocationProbe() {
    const location = useLocation()
    return <div data-testid="location">{location.pathname}{location.search}</div>
}

describe('DshPage navigation', () => {
    it('renders the sections in the content area and keeps selection in the URL', () => {
        const user = {
            user_id: 1,
            user_name: 'admin',
            role: 'admin',
        }
        const contextValue = {
            user,
            setUser: vi.fn(),
            savedComponents: [],
            addSavedComponent: vi.fn(),
            checkComponentsName: vi.fn(),
            delComponent: vi.fn(),
        }

        render(
            <MemoryRouter initialEntries={['/dsh?tab=usage']}>
                <userContext.Provider value={contextValue}>
                    <DshPage />
                    <LocationProbe />
                </userContext.Provider>
            </MemoryRouter>,
        )

        const tablist = screen.getByRole('tablist', { name: 'dsh.title' })
        expect(tablist.closest('.px-2')).toBeTruthy()
        expect(screen.getAllByRole('tab')).toHaveLength(5)
        expect(screen.queryByRole('tab', { name: 'dsh.operations' })).toBeNull()
        expect(screen.getByRole('tab', { name: 'dsh.userUsage' })).toHaveAttribute(
            'data-state',
            'active',
        )

        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.accessSettings' }), {
            button: 0,
            ctrlKey: false,
        })

        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=access')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('access')

        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.enterprisePlugins' }), {
            button: 0,
            ctrlKey: false,
        })

        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=plugins')
        expect(screen.getByTestId('plugin-market')).toBeInTheDocument()
    })

    it('opens the available default section for a saved audit URL', () => {
        const contextValue = {
            user: { user_id: 1, user_name: 'admin', role: 'admin' },
            setUser: vi.fn(), savedComponents: [], addSavedComponent: vi.fn(),
            checkComponentsName: vi.fn(), delComponent: vi.fn(),
        }
        render(
            <MemoryRouter initialEntries={['/dsh?tab=operations']}>
                <userContext.Provider value={contextValue}>
                    <DshPage />
                </userContext.Provider>
            </MemoryRouter>,
        )
        expect(screen.queryByRole('tab', { name: 'dsh.operations' })).toBeNull()
        expect(screen.getByRole('tab', { name: 'dsh.licenseAndSeats' })).toHaveAttribute('data-state', 'active')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('license')
        expect(resolveDshSection('?tab=operations')).toBe('license')
        expect(resolveDshSection('?tab=operations', ['access'])).toBe('access')
    })
})
