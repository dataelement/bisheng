import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { userContext } from '@/contexts/userContext'
import DshPage from '.'
import { resolveDshSection } from './sections'

const browserConfig = vi.hoisted(() => ({ enabled: true, managementEnabled: true }))

vi.mock('@/hooks/useDshBrowserConfig', () => ({
    useDshBrowserConfig: () => ({
        config: {
            management_enabled: browserConfig.managementEnabled,
            enabled: browserConfig.enabled,
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
    beforeEach(() => {
        browserConfig.enabled = true
        browserConfig.managementEnabled = true
    })
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
        const tabs = screen.getAllByRole('tab')
        const labels = [
            'dsh.unified.credits', 'dsh.unified.usage', 'dsh.unified.models',
            'dsh.auditTab', 'dsh.contentSafety.title', 'dsh.accessSettings',
            'dsh.enterprisePlugins',
        ]
        expect(tabs).toHaveLength(labels.length)
        labels.forEach((label, index) => expect(tabs[index]).toHaveAccessibleName(label))
        expect(screen.queryByRole('tab', { name: 'dsh.operations' })).toBeNull()
        expect(screen.getByRole('tab', { name: 'dsh.unified.usage' })).toHaveAttribute(
            'data-state',
            'active',
        )

        expect(screen.getByTestId('dsh-section')).toHaveTextContent('usage')
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.unified.credits' }), {
            button: 0,
            ctrlKey: false,
        })
        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=credits')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('credits')

        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.unified.models' }), {
            button: 0,
            ctrlKey: false,
        })
        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=models')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('models')

        expect(screen.queryByRole('tab', { name: 'dsh.modelAudit' })).toBeNull()
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.auditTab' }), {
            button: 0,
            ctrlKey: false,
        })
        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=model-audit')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('model-audit')

        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.contentSafety.title' }), {
            button: 0,
            ctrlKey: false,
        })
        expect(screen.getByTestId('location')).toHaveTextContent('/dsh?tab=content-safety')
        expect(screen.getByRole('heading', { name: 'dsh.contentSafety.title' })).toBeInTheDocument()

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
        expect(screen.getByRole('tab', { name: 'dsh.unified.credits' })).toHaveAttribute('data-state', 'active')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('credits')
        expect(resolveDshSection('?tab=operations')).toBe('credits')
        expect(resolveDshSection('?tab=operations', ['access'])).toBe('access')
    })

    it.each(['', '?tab=unknown', '?tab=operations'])('defaults to credits for %s', search => {
        renderPage(`/dsh${search}`)
        expect(screen.getByRole('tab', { name: 'dsh.unified.credits' })).toHaveAttribute('data-state', 'active')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('credits')
        expect(resolveDshSection(search)).toBe('credits')
        expect(resolveDshSection(search, [])).toBe('credits')
    })

    it.each(['credits', 'models', 'content-safety', 'operations', 'unknown'])('keeps only access available when DSH is disabled: %s', section => {
        browserConfig.enabled = false
        renderPage(`/dsh?tab=${section}`)
        expect(screen.getAllByRole('tab')).toHaveLength(1)
        expect(screen.getByRole('tab', { name: 'dsh.accessSettings' })).toHaveAttribute('data-state', 'active')
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('access')
        expect(screen.queryByRole('heading', { name: 'dsh.contentSafety.title' })).toBeNull()
    })

    it('redirects ordinary users without exposing management tabs', () => {
        renderPage('/dsh?tab=content-safety', { user_id: 2, user_name: 'user', role: 'user' })
        expect(screen.getByTestId('location')).toHaveTextContent('/403')
        expect(screen.queryByRole('tab')).toBeNull()
        expect(screen.queryByRole('heading', { name: 'dsh.contentSafety.title' })).toBeNull()
    })

    it.each([
        { user_id: 3, user_name: 'global', role: 'user', is_global_super: true },
        { user_id: 4, user_name: 'child', role: 'user', is_child_admin: true },
    ])('preserves management access for $user_name administrators', user => {
        renderPage('/dsh', user)
        expect(screen.getAllByRole('tab')).toHaveLength(7)
        expect(screen.getByTestId('dsh-section')).toHaveTextContent('credits')
        expect(screen.getByRole('tab', { name: 'dsh.contentSafety.title' })).toBeInTheDocument()
    })

    it('keeps navigation hidden when management is unavailable', () => {
        browserConfig.managementEnabled = false
        renderPage('/dsh?tab=content-safety')
        expect(screen.queryByRole('tab')).toBeNull()
        expect(screen.getByText('dsh.managementUnavailable')).toBeInTheDocument()
        expect(screen.queryByRole('heading', { name: 'dsh.contentSafety.title' })).toBeNull()
    })
})

function renderPage(
    initialEntry: string,
    user: { user_id: number; user_name: string; role: string; is_global_super?: boolean; is_child_admin?: boolean } = {
        user_id: 1, user_name: 'admin', role: 'admin',
    },
) {
    const contextValue = {
        user,
        setUser: vi.fn(), savedComponents: [], addSavedComponent: vi.fn(),
        checkComponentsName: vi.fn(), delComponent: vi.fn(),
    }
    return render(
        <MemoryRouter initialEntries={[initialEntry]}>
            <userContext.Provider value={contextValue}>
                <DshPage />
                <LocationProbe />
            </userContext.Provider>
        </MemoryRouter>,
    )
}
