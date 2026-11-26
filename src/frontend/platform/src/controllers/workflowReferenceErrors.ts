import i18next from 'i18next';
import { referenceErrorMessage } from '@bisheng/api-client';

export function workflowReferenceErrorMessage(envelope: unknown): string {
    return referenceErrorMessage(envelope, (key, values) => String(i18next.t(`api_errors:${key}`, values)));
}
