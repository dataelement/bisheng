import { useEffect, useState } from 'react';
import { useAuthContext } from '~/hooks';
import type { HomeSort } from './homeSpaces';

function readSort(storageKey: string | undefined): HomeSort {
  if (!storageKey) return 'create_time';
  try {
    const saved = window.localStorage.getItem(storageKey);
    return saved === 'name' || saved === 'update_time' ? saved : 'create_time';
  } catch {
    return 'create_time';
  }
}

/** Keep the list preference across page mounts, scoped to the signed-in account. */
export function useKnowledgeHomeSort() {
  const { user } = useAuthContext();
  // AuthContext clears bs:* chat settings on a fresh login; list preferences are independent.
  const storageKey = user?.id == null ? undefined : `knowledge-home-sort:${user.id}`;
  const [selection, setSelection] = useState(() => ({ storageKey, value: readSort(storageKey) }));

  useEffect(() => {
    setSelection({ storageKey, value: readSort(storageKey) });
  }, [storageKey]);

  // Never render another account's selection while its preference is being restored.
  const sort = selection.storageKey === storageKey ? selection.value : readSort(storageKey);
  const handleSortChange = (value: HomeSort) => {
    setSelection({ storageKey, value });
    if (!storageKey) return;
    try {
      window.localStorage.setItem(storageKey, value);
    } catch {
      // Keep the current selection usable when browser storage is unavailable.
    }
  };

  return [sort, handleSortChange] as const;
}
