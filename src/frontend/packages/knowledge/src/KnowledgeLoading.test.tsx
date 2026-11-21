// @vitest-environment jsdom

import { LoadingIndicatorProvider } from '@bisheng/ui';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps, ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MoveToDialog } from './MoveToDialog';
import { RelateDocumentPanel } from './RelateDocumentPanel';
import { SimilarDocumentDialog } from './SimilarDocumentDialog';
import type { SimilarDocumentsServices } from './types';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}

function configured(children: ReactNode) {
  return <LoadingIndicatorProvider renderIndicator={({ className }) => <svg data-testid="configured-loading" className={className} />}>
    {children}
  </LoadingIndicatorProvider>;
}

function similarServices(overrides: Partial<SimilarDocumentsServices> = {}): SimilarDocumentsServices {
  return {
    getRecommendations: vi.fn(async () => []),
    searchDocuments: vi.fn(async () => []),
    relate: vi.fn(async () => ({ document_id: 1, new_version_no: 2 })),
    dismiss: vi.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('host-configured knowledge loading', () => {
  it('uses configured loading for recommendation and search requests until their results arrive', async () => {
    const recommendations = deferred<[]>();
    const results = deferred<[]>();
    const services = similarServices({
      getRecommendations: vi.fn(() => recommendations.promise),
      searchDocuments: vi.fn(() => results.promise),
    });
    const { container } = render(configured(<RelateDocumentPanel spaceId={1} file={{ id: 2, name: 'Document.txt' }}
      services={services} onError={vi.fn()} onSuccess={vi.fn()} />));

    expect(screen.getByTestId('configured-loading').classList.contains('size-10')).toBe(true);
    expect(container.querySelector('.lucide-loader-circle')).toBeNull();
    expect(screen.getByRole('status', { name: 'loading' }).textContent).toBe('');

    await act(async () => recommendations.resolve([]));
    expect(screen.queryByTestId('configured-loading')).toBeNull();
    expect(screen.getByText('no_recommendations')).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText('search_placeholder'), { target: { value: 'Document' } });
    fireEvent.click(screen.getByRole('button', { name: 'search_button' }));
    expect(screen.getByTestId('configured-loading')).toBeTruthy();
    expect(services.searchDocuments).toHaveBeenCalledWith(1, 'Document', 2, expect.any(AbortSignal));

    await act(async () => results.resolve([]));
    expect(screen.queryByTestId('configured-loading')).toBeNull();
    expect(screen.getByText('no_search_results')).toBeTruthy();
  });

  it('keeps the default similar-document indicator outside a provider and replaces it inside the host', async () => {
    const pending = deferred<[]>();
    const props: ComponentProps<typeof SimilarDocumentDialog> = {
      open: true,
      onOpenChange: vi.fn(),
      spaceId: 1,
      services: { ...similarServices(), getPending: vi.fn(() => pending.promise) },
      onError: vi.fn(),
      onSuccess: vi.fn(),
    };
    const view = render(<SimilarDocumentDialog {...props} />);
    expect(screen.getByRole('status', { name: 'loading' }).querySelector('.animate-spin')).not.toBeNull();
    expect(screen.queryByTestId('configured-loading')).toBeNull();

    view.rerender(configured(<SimilarDocumentDialog {...props} />));
    expect(screen.getByTestId('configured-loading').classList.contains('size-10')).toBe(true);
    expect(screen.getByRole('status', { name: 'loading' }).textContent).toBe('');

    await act(async () => pending.resolve([]));
    expect(screen.queryByTestId('configured-loading')).toBeNull();
    expect(screen.getByText('similar_dialog_empty')).toBeTruthy();
  });

  it('replaces both move panes while preserving the default client catalog text and disabled confirmation', async () => {
    type Services = ComponentProps<typeof MoveToDialog>['services'];
    const catalog = deferred<Awaited<ReturnType<Services['listSpaces']>>>();
    const contents = deferred<[]>();
    const services: Services = {
      listSpaces: vi.fn(() => catalog.promise),
      listChildren: vi.fn(() => contents.promise),
      listFolders: vi.fn(async () => []),
    };
    const props: ComponentProps<typeof MoveToDialog> = {
      open: true,
      onOpenChange: vi.fn(),
      currentSpaceId: 'source',
      services,
      onError: vi.fn(),
      onConfirm: vi.fn(),
    };
    const view = render(<MoveToDialog {...props} />);
    expect(screen.getByText('loading')).toBeTruthy();
    expect(screen.queryByTestId('configured-loading')).toBeNull();

    view.rerender(configured(<MoveToDialog {...props} />));
    expect(screen.queryByText('loading')).toBeNull();
    expect(screen.getAllByTestId('configured-loading').length).toBeGreaterThan(0);
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'move_here' }).disabled).toBe(true);

    await act(async () => catalog.resolve({ department: [], created: [{ id: 'source', name: 'Source' }], joined: [] }));
    expect(screen.getAllByTestId('configured-loading')).toHaveLength(1);
    expect(screen.getByTestId('configured-loading').classList.contains('size-10')).toBe(true);
    expect(screen.queryByText('loading')).toBeNull();

    await act(async () => contents.resolve([]));
    expect(screen.queryByTestId('configured-loading')).toBeNull();
    expect(screen.getByText('empty_folder')).toBeTruthy();
    expect(props.onConfirm).not.toHaveBeenCalled();
  });
});
