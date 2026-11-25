import { readWorkspaceLanguage, saveWorkspaceLanguage } from '~/locales/workspaceLanguage';
import { atomWithLocalStorage } from './utils';

const lang = atomWithLocalStorage<string>('lang', readWorkspaceLanguage(), {
  read: readWorkspaceLanguage,
  write: saveWorkspaceLanguage,
});

export default { lang };
