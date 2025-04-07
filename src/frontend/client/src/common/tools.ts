import type { AuthType } from '~/data-provider/data-provider/src';

export type ApiKeyFormData = {
  apiKey: string;
  authType?: string | AuthType;
};
