import { MutationObserver, QueryObserver, onlineManager } from '@tanstack/react-query';
import { waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from './queryClient';

afterEach(() => onlineManager.setOnline(true));

it('keeps intranet queries running even when the browser reports offline', async () => {
  const client = createPlatformQueryClient();
  client.mount();
  onlineManager.setOnline(false);
  const fetch = vi.fn().mockResolvedValue(['department']);
  const pending = client.fetchQuery(['departments'], fetch);
  try {
    expect(client.getQueryState(['departments'])?.fetchStatus).toBe('fetching');
    await waitFor(() => expect(fetch).toHaveBeenCalled(), { timeout: 100 });
  } finally {
    onlineManager.setOnline(true);
    await pending;
    client.clear();
    client.unmount();
  }
});

it('keeps save operations running even when the browser reports offline', async () => {
  const client = createPlatformQueryClient();
  client.mount();
  onlineManager.setOnline(false);
  const save = vi.fn().mockResolvedValue({ id: 1 });
  const mutation = new MutationObserver(client, { mutationFn: save });
  const pending = mutation.mutate();
  try {
    await waitFor(() => expect(save).toHaveBeenCalled(), { timeout: 100 });
  } finally {
    onlineManager.setOnline(true);
    await pending;
    client.clear();
    client.unmount();
  }
});

it('retains the v3 refresh-on-reconnect behavior for a stale active query', async () => {
  const client = createPlatformQueryClient();
  const fetch = vi.fn().mockResolvedValue(['model']);
  client.mount();
  const observer = new QueryObserver(client, { queryKey: ['reconnect'], queryFn: fetch });
  const unsubscribe = observer.subscribe(() => undefined);
  try {
    await client.fetchQuery(['reconnect'], fetch);
    expect(fetch).toHaveBeenCalledTimes(1);
    onlineManager.setOnline(false);
    onlineManager.setOnline(true);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2), { timeout: 150 });
  } finally {
    unsubscribe(); client.unmount(); client.clear();
  }
});
