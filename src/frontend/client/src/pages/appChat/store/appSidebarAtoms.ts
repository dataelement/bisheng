import { atom } from 'recoil';
import type { AppItem, AppConversation } from '~/@types/app';

/** Current app info displayed in sidebar */
export const currentAppInfoState = atom<AppItem | null>({
  key: 'currentAppInfoState',
  default: null,
});

/** All conversations for current app */
export const appConversationsState = atom<AppConversation[]>({
  key: 'appConversationsState',
  default: [],
});

/** Sidebar visibility (persisted to localStorage) */
export const sidebarVisibleState = atom<boolean>({
  key: 'sidebarVisibleState',
  default: true,
  effects: [
    ({ setSelf, onSet }) => {
      const key = 'app_sidebar_visible';
      const saved = localStorage.getItem(key);
      if (saved !== null) setSelf(JSON.parse(saved));
      onSet((newVal) => localStorage.setItem(key, JSON.stringify(newVal)));
    },
  ],
});
