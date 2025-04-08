import { atomWithLocalStorage } from '~/store/utils';

const modelType = atomWithLocalStorage('modelType', '');
const searchType = atomWithLocalStorage('searchType', '');
const isSearch = atomWithLocalStorage('isSearch', false);

const chatModel = atomWithLocalStorage('chatModel', { id: 0, name: '' });

export default {
  modelType,
  searchType,
  isSearch,
  chatModel
};
