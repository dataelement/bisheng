import { atom } from 'recoil';

// Current active chatId in standalone chat mode (not reflected in URL)
export const standaloneChatIdState = atom<string>({
  key: 'standaloneChatIdState',
  default: '',
});
