import { atom } from 'recoil';
import { TAttachment } from '~/types/chat';
import { atomWithLocalStorage } from './utils';

const hideBannerHint = atomWithLocalStorage('hideBannerHint', [] as string[]);

const messageAttachmentsMap = atom<Record<string, TAttachment[] | undefined>>({
  key: 'messageAttachmentsMap',
  default: {},
});

const queriesEnabled = atom<boolean>({
  key: 'queriesEnabled',
  default: true,
});

/** 主站会话历史抽屉（与 Root 原 navVisible 共用 localStorage key `navVisible`） */
const chatHistoryDrawerOpen = atomWithLocalStorage<boolean>('navVisible', true);

export default { hideBannerHint, messageAttachmentsMap, queriesEnabled, chatHistoryDrawerOpen };
