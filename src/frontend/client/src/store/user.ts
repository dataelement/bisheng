import { atom } from 'recoil';
import type { TUser, TPlugin } from '~/data-provider/data-provider/src';

const user = atom<TUser | undefined>({
  key: 'user',
  default: undefined,
});

const availableTools = atom<Record<string, TPlugin>>({
  key: 'availableTools',
  default: {},
});

export default {
  user,
  availableTools,
};
