import { atomWithLocalStorage } from '~/store/utils';

const modelType = atomWithLocalStorage('modelType', '');
const searchType = atomWithLocalStorage('searchType', '');
const isSearch = atomWithLocalStorage('isSearch', false);

export default {
  modelType,
  searchType,
  isSearch,
};
