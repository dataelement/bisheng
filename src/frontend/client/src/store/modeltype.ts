import { atomWithLocalStorage } from '~/store/utils';
export type SelectedOrgKb = {
  id: string;
  name: string;
};
const modelType = atomWithLocalStorage('modelType', '');
const searchType = atomWithLocalStorage('searchType', '');
const isSearch = atomWithLocalStorage('isSearch', false);

const chatModel = atomWithLocalStorage('chatModel', { id: 0, name: '' });

const selectedOrgKbs = atomWithLocalStorage<SelectedOrgKb[]>(
  'selectedOrgKbs',
  []
);

const enableOrgKb = atomWithLocalStorage<boolean>(
  'enableOrgKb',
  false
);
export default {
  modelType,
  searchType,
  isSearch,
  chatModel,
  selectedOrgKbs,
  enableOrgKb,  
};
