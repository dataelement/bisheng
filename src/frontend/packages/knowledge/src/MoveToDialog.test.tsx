// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MoveToDialog } from './MoveToDialog';

vi.mock('react-i18next', () => {
  const t = (key: string, options?: { name?: string }) =>
    options?.name ? `${key} ${options.name}` : key;
  return { useTranslation: () => ({ t }) };
});

type MoveServices = ComponentProps<typeof MoveToDialog>['services'];
type SpaceCatalog = Awaited<ReturnType<MoveServices['listSpaces']>>;
type DestinationItems = Awaited<ReturnType<MoveServices['listChildren']>>;

const catalog: SpaceCatalog = {
  department: [{ id: 'department', name: 'Department space' }],
  created: [
    { id: 'source', name: 'Source space' },
    { id: 'target', name: 'Target space' },
  ],
  joined: [{ id: 'joined', name: 'Joined space' }],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}

function createServices(overrides: Partial<MoveServices> = {}): MoveServices {
  return {
    listSpaces: vi.fn<MoveServices['listSpaces']>(async () => catalog),
    listFolders: vi.fn<MoveServices['listFolders']>(async (spaceId, parentId) =>
      spaceId === 'source' && parentId === null
        ? [{ id: 'shared-id', name: 'Folder A' }]
        : []),
    listChildren: vi.fn<MoveServices['listChildren']>(async (spaceId, parentId) => {
      if (spaceId !== 'source') return [];
      if (parentId !== null)
        return [{ id: 'nested', name: 'Nested document.txt', type: 'file' as const }];
      return [
        { id: 'shared-id', name: 'Folder A', type: 'folder' as const },
        { id: 'shared-id', name: 'Document.pdf', type: 'file' as const },
      ];
    }),
    ...overrides,
  };
}

function propsFor(services = createServices()) {
  return {
    open: true,
    onOpenChange: vi.fn(),
    currentSpaceId: 'source',
    currentSpaceName: 'Source space',
    services,
    onError: vi.fn(),
    onConfirm: vi.fn(),
  } satisfies ComponentProps<typeof MoveToDialog>;
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
    window.setTimeout(() => callback(0), 0));
  vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('MoveToDialog', () => {
  it('defaults to the current writable space and keeps folder and file IDs independent', async () => {
    const props = propsFor();
    render(<MoveToDialog {...props} />);

    await screen.findByTitle('Source space');
    await screen.findByText('Document.pdf');
    expect(screen.getByTitle('Source space').getAttribute('aria-current')).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'move_here' }).disabled).toBe(false);
    expect(screen.queryByRole('button', { name: 'Document.pdf' })).toBeNull();
    expect(screen.getByText('Document.pdf').closest('[aria-disabled="true"]')).not.toBeNull();
    expect(screen.getAllByRole('button', { name: 'Folder A', exact: true }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'move_here' }));

    expect(props.onConfirm).toHaveBeenCalledWith('source', null, false, undefined);
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows a partial catalog before the full space list resolves', async () => {
    const pending = deferred<SpaceCatalog>();
    const services = createServices({
      listSpaces: vi.fn(async (_signal, hooks) => {
        hooks?.onPartial?.({
          department: [],
          created: [{ id: 'source', name: 'Source space' }],
          joined: [],
        });
        return pending.promise;
      }),
    });
    render(<MoveToDialog {...propsFor(services)} />);

    await screen.findByTitle('Source space');
    expect(screen.queryByText('loading')).toBeNull();
    pending.resolve(catalog);
  });

  it('asks a host that can search on the server once the typed name settles', async () => {
    const searchSpaces = vi.fn<NonNullable<MoveServices['searchSpaces']>>(async () => ({
      department: [],
      created: [{ id: 'target', name: 'New space' }],
      joined: [],
    }));
    const services = createServices({ searchSpaces });
    render(<MoveToDialog {...propsFor(services)} />);
    await screen.findByTitle('Source space');

    fireEvent.change(screen.getByPlaceholderText('search_placeholder'), {
      target: { value: 'New space' },
    });

    await waitFor(() => expect(searchSpaces).toHaveBeenCalled());
    expect(searchSpaces.mock.calls[0]?.[0]).toBe('New space');
    await screen.findByTitle('New space');
  });

  it('keeps the chosen folder while filtering spaces by name', async () => {
    const props = propsFor();
    render(<MoveToDialog {...props} />);

    fireEvent.click(await screen.findByTitle('Folder A'));
    await screen.findByText('Nested document.txt');
    fireEvent.change(screen.getByPlaceholderText('search_placeholder'), {
      target: { value: 'Target space' },
    });
    await waitFor(() => expect(screen.queryByTitle('Source space')).toBeNull());
    expect(screen.getByTitle('Target space')).toBeTruthy();
    expect(screen.getByText('Nested document.txt')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'move_here' }));

    expect(props.onConfirm).toHaveBeenCalledWith('source', 'shared-id', false, 'Folder A');
  });

  it('closes the picker before submitting a cross-space destination', async () => {
    const events: string[] = [];
    const props = propsFor();
    props.onOpenChange.mockImplementation(() => { events.push('close'); });
    props.onConfirm.mockImplementation(() => { events.push('confirm'); });
    render(<MoveToDialog {...props} />);

    fireEvent.click(await screen.findByTitle('Target space'));
    fireEvent.click(screen.getByRole('button', { name: 'move_here' }));

    expect(props.onConfirm).toHaveBeenCalledWith('target', null, true, undefined);
    expect(events).toEqual(['close', 'confirm']);
  });

  it('cancels without submitting a move', async () => {
    const props = propsFor();
    render(<MoveToDialog {...props} />);
    await screen.findByTitle('Source space');

    fireEvent.click(screen.getByRole('button', { name: 'cancel' }));

    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it('surfaces a failed catalog read and lets the user retry it', async () => {
    const error = new Error('Catalog is unavailable');
    const services = createServices({
      listSpaces: vi.fn<MoveServices['listSpaces']>()
        .mockRejectedValueOnce(error)
        .mockResolvedValueOnce(catalog),
    });
    const props = propsFor(services);
    render(<MoveToDialog {...props} />);

    const retry = await screen.findByRole('button', { name: 'retry' });
    expect(props.onError).toHaveBeenCalledWith(error);
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'move_here' }).disabled).toBe(true);
    fireEvent.click(retry);

    await screen.findByTitle('Source space');
    await waitFor(() => expect(screen.getByRole<HTMLButtonElement>('button', { name: 'move_here' }).disabled).toBe(false));
    expect(services.listSpaces).toHaveBeenCalledTimes(2);
  });

  it('ignores a retired catalog response after changing services', async () => {
    const retired = deferred<SpaceCatalog>();
    const oldServices = createServices({ listSpaces: vi.fn(() => retired.promise) });
    const props = propsFor(oldServices);
    const { rerender } = render(<MoveToDialog {...props} />);
    await waitFor(() => expect(oldServices.listSpaces).toHaveBeenCalledOnce());

    const nextServices = createServices();
    rerender(<MoveToDialog {...props} services={nextServices} />);
    await screen.findByTitle('Source space');
    fireEvent.click(screen.getByTitle('Target space'));
    await act(async () => {
      retired.resolve({
        department: [],
        created: [{ id: 'retired', name: 'Retired space' }],
        joined: [],
      });
    });

    expect(screen.queryByTitle('Retired space')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'move_here' }));
    expect(props.onConfirm).toHaveBeenCalledWith('target', null, true, undefined);
  });

  it('ignores a retired contents response after closing and reopening', async () => {
    const retired = deferred<DestinationItems>();
    const oldServices = createServices({ listChildren: vi.fn(() => retired.promise) });
    const props = propsFor(oldServices);
    const { rerender } = render(<MoveToDialog {...props} />);
    await waitFor(() => expect(oldServices.listChildren).toHaveBeenCalled());

    rerender(<MoveToDialog {...props} open={false} />);
    await act(async () => {
      retired.resolve([{ id: 'retired', name: 'Retired document.txt', type: 'file' }]);
    });
    rerender(<MoveToDialog {...props} services={createServices()} />);

    await screen.findByText('Document.pdf');
    expect(screen.queryByText('Retired document.txt')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'move_here' }));
    expect(props.onConfirm).toHaveBeenCalledWith('source', null, false, undefined);
  });
});
