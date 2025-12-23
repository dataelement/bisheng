import { atomWithLocalStorage } from '~/store/utils';
import { atom } from 'recoil';

export type SelectedOrgKb = {
  id: string;
  name: string;
};
const modelType = atomWithLocalStorage('modelType', '');
const searchType = atomWithLocalStorage('searchType', '');
const isSearch = atomWithLocalStorage('isSearch', false);

const chatModel = atomWithLocalStorage('chatModel', { id: 0, name: '' });

const selectedOrgKbs = atom<SelectedOrgKb[]>({
  key: 'selectedOrgKbs',
  default: []
});

const chatId = atom({
  key: 'chatId',
  default: ''
});

const enableOrgKb = atom<boolean>({
  key: 'enableOrgKb',
  default: false
});

const chatStatesMap = atom<Record<string, any>>({
  key: 'chatStatesMap',
  default: {}
});

export default {
  modelType,
  searchType,
  isSearch,
  chatModel,
  selectedOrgKbs,
  enableOrgKb,
  chatId,
  chatStatesMap,
};
