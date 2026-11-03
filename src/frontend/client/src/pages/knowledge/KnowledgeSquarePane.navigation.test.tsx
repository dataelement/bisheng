import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import type { KnowledgeSpace } from '~/api/knowledge';
import { useDesktopNavigation } from '~/components/Chat/useDesktopNavigation';
import { KnowledgeSquarePane } from './KnowledgeSquarePane';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => true }));
jest.mock('./KnowledgeSquare', () => ({
    __esModule: true,
    default: ({ onPreviewSpace }: { onPreviewSpace: (space: KnowledgeSpace) => void }) => (
        <><input aria-label="Search spaces" /><button onClick={() => onPreviewSpace({ id: '77', name: 'Approval space' } as KnowledgeSpace)}>Open space</button></>
    ),
}));
jest.mock('./KnowledgeSpacePreviewDrawer', () => ({
    KnowledgeSpacePreviewDrawer: ({ spaceId, open, onOpenChange }: { spaceId?: string; open: boolean; onOpenChange: (open: boolean) => void }) => (
        open ? <div role="dialog" aria-label={`Space ${spaceId}`}><button onClick={() => onOpenChange(false)}>Back to square</button></div> : null
    ),
}));

function Host() {
    useDesktopNavigation();
    const location = useLocation();
    const navigate = useNavigate();
    return <>
        <output data-testid="path">{location.pathname + location.search}</output>
        <button onClick={() => {
            // The native host skips same-URL navigation before publishing its event.
            if (location.pathname + location.search === '/square') return;
            window.dispatchEvent(new CustomEvent('dsh:navigate', { detail: { path: '/square' }, cancelable: true }));
        }}>Discover square</button>
        <button onClick={() => navigate(-1)}>History back</button>
        <button onClick={() => navigate(1)}>History forward</button>
        <KnowledgeSquarePane />
    </>;
}

function setup(path = '/square?type=knowledge') {
    render(<MemoryRouter initialEntries={[path]}><Host /></MemoryRouter>);
}

it('represents the open preview in the URL and preserves square context when closing', () => {
    setup('/square?type=knowledge&source=menu');
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Approval' } });
    fireEvent.click(screen.getByText('Open space'));
    expect(screen.getByTestId('path')).toHaveTextContent('/square?type=knowledge&source=menu&previewSpace=77');
    expect(screen.getByRole('dialog', { name: 'Space 77' })).toBeVisible();
    fireEvent.click(screen.getByText('Back to square'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('path')).toHaveTextContent('/square?type=knowledge&source=menu');
    expect(screen.getByRole('textbox')).toHaveValue('Approval');
});

it.each(['/square', '/square?type=knowledge'])('reselecting the desktop square closes preview from %s', path => {
    setup(path);
    fireEvent.click(screen.getByText('Open space'));
    fireEvent.click(screen.getByText('Discover square'));
    expect(screen.getByTestId('path')).toHaveTextContent(/^\/square$/);
    expect(screen.queryByRole('dialog')).toBeNull();
});

it('supports history Back and Forward through preview navigation', () => {
    setup();
    fireEvent.click(screen.getByText('Open space'));
    fireEvent.click(screen.getByText('History back'));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByText('History forward'));
    expect(screen.getByRole('dialog', { name: 'Space 77' })).toBeVisible();
});

it('opens a directly loaded preview and closes it to the source category', () => {
    setup('/square?type=knowledge&previewSpace=77');
    expect(screen.getByRole('dialog', { name: 'Space 77' })).toBeVisible();
    fireEvent.click(screen.getByText('Back to square'));
    expect(screen.getByTestId('path')).toHaveTextContent('/square?type=knowledge');
});
