import type { AuthType } from '~/types/chat';

export type ApiKeyFormData = {
  apiKey: string;
  authType?: string | AuthType;
};
