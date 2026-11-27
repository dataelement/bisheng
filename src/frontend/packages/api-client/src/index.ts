export { ApiError, decodeErrorEnvelope, isApiError, isErrorEnvelope, normalizeApiError, shouldRetryApiError, resolveErrorMessageTemplate } from './apiError';
export type { ApiErrorKind, ApiErrorResponse, ErrorEnvelope, ErrorPresentation } from './apiError';
export { BrowserScopeSession, needsBrowserScope, hasIndependentScope, isScopeReconfirmationChange } from './browserScope';
export { DSH_BROWSER_CONFIG_QUERY_KEY, DSH_BROWSER_CONFIG_CACHE_OPTIONS, notifyDshBrowserConfigChanged, subscribeDshBrowserConfigChanges } from './dshBrowserConfig';

export { referenceErrorMessage } from './referenceErrors';
export { BrowserAuthSession, isPlatformAuthPath, isAccessExpired, isDefinitiveAuthFailure, authFailureCode } from './authSession';
export { AuthSessionError } from './authTypes';
export type { AuthSessionMetadata, AuthTransport, AuthEnvironment, AuthEvent, PlatformLoginInput } from './authTypes';
export { requestHostAuthRenewal } from './authCoordination';
