import { LocalStorageKeys } from '~/data-provider/data-provider/src';

export default function useSetFilesToDelete() {
  const setFilesToDelete = (files: Record<string, unknown>) =>
    localStorage.setItem(LocalStorageKeys.FILES_TO_DELETE, JSON.stringify(files));
  return setFilesToDelete;
}
