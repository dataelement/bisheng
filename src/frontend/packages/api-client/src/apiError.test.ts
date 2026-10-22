import { describe, expect, it } from 'vitest';
import { normalizeApiError, shouldRetryApiError, decodeErrorEnvelope, resolveErrorMessageTemplate } from './apiError';

describe('request failure evidence', () => {
  it('retains independent HTTP status and business evidence', () => {
    const response = { status: 409, data: { status_code: 26130, status_message: 'conflict', data: { version: 7 } }, headers: { trace: 'id' } };
    const cause = Object.assign(new Error('HTTP 409'), { response });
    const error = normalizeApiError(cause, { message: 'Translated conflict' });
    expect(error).toBeInstanceOf(Error);
    expect(error).toMatchObject({ message: 'Translated conflict', kind: 'http', httpStatus: 409, status_code: 26130, data: { version: 7 }, presentation: 'none' });
    expect(error.response).toBe(response);
    expect(error.cause).toBe(cause);
    expect(normalizeApiError(error, { message: 'Do not replace' })).toBe(error);
  });

  it.each([200, 400])('preserves binary and decoded evidence together for HTTP %s', async (status) => {
    const blob = new Blob([JSON.stringify({ status_code: 12064, status_message: 'failed', data: { file: 'report' } })], { type: 'application/json' });
    const response = { status, data: blob };
    const cause = Object.assign(new Error('download failed'), { response });
    const envelope = await decodeErrorEnvelope(blob);
    const error = normalizeApiError(cause, { message: 'Export failed', response, envelope });
    expect(error.status_code).toBe(12064);
    expect(error.data).toEqual({ file: 'report' });
    expect(error.httpStatus).toBe(status);
    expect(error.response).toBe(response);
    expect(error.response?.data).toBe(blob);
    expect(error.cause).toBe(cause);
    expect(error.kind).toBe(status === 200 ? 'business' : 'http');
  });

  it('prefers explicit decoded evidence without overwriting the response', () => {
    const response = { status: 400, data: { status_code: 500, data: { wrong: true } } };
    const error = normalizeApiError({ response }, { message: 'failed', envelope: { status_code: 12064, data: { correct: true } } });
    expect(error.status_code).toBe(12064);
    expect(error.data).toEqual({ correct: true });
    expect(response.data.status_code).toBe(500);
  });

  it.each([
    ['ERR_CANCELED', 'canceled', false],
    ['ECONNABORTED', 'timeout', true],
    ['ETIMEDOUT', 'timeout', true],
    ['ERR_NETWORK', 'network', true],
  ])('keeps transport identity for %s', (code, kind, retry) => {
    const error = normalizeApiError({ code }, { message: 'failed' });
    expect(error).toMatchObject({ code, kind });
    expect(error.httpStatus).toBeUndefined();
    expect(error.status_code).toBeUndefined();
    expect(shouldRetryApiError(error)).toBe(retry);
  });

  it('does not activate retries for newly surfaced business errors or global handling', () => {
    const business = normalizeApiError({ status_code: 11055 }, { message: 'duplicate' });
    expect(shouldRetryApiError(business)).toBe(false);
    const http = normalizeApiError({ response: { status: 503, data: {} } }, { message: 'unavailable' });
    expect(shouldRetryApiError(http)).toBe(true);
    http.presentation = 'global';
    expect(shouldRetryApiError(http)).toBe(false);
  });

  it('does not treat arbitrary JSON downloads or malformed binary as errors', async () => {
    expect(await decodeErrorEnvelope(new Blob(['{"name":"report"}'], { type: 'application/json' }))).toBeUndefined();
    expect(await decodeErrorEnvelope(new Blob(['not JSON'], { type: 'application/json' }))).toBeUndefined();
    expect(await decodeErrorEnvelope(new Blob(['binary'], { type: 'application/pdf' }))).toBeUndefined();
    expect(await decodeErrorEnvelope(new TextEncoder().encode('{"status_code":12064}').buffer)).toEqual({ status_code: 12064 });
  });
});

it('decodes an untyped binary error only when the transport failed', async () => {
  const blob = new Blob(['{"status_code":10604,"data":{"session":"revoked"}}']);
  expect(await decodeErrorEnvelope(blob)).toBeUndefined();
  expect(await decodeErrorEnvelope(blob, { httpFailure: true })).toMatchObject({ status_code: 10604, data: { session: 'revoked' } });
});

it('renders available error parameters and never exposes unresolved placeholders', () => {
  expect(resolveErrorMessageTemplate('Storage {{used}}/{quota} GB', { used: 2, quota: 3 }, 'Request failed')).toBe('Storage 2/3 GB');
  expect(resolveErrorMessageTemplate('Validation failed: {field}', { field: 'name' }, 'Request failed')).toBe('Validation failed: name');
  expect(resolveErrorMessageTemplate('Validation failed: {missing}', {}, 'Request failed')).toBe('Request failed');
});

describe('readable transport failures', () => {
  const transportMessages = { network: 'Cannot connect. Check your network and try again.', timeout: 'The request timed out. Check the result before retrying.' };

  it.each([
    ['ERR_NETWORK', 'network', 'Cannot connect. Check your network and try again.'],
    ['ECONNABORTED', 'timeout', 'The request timed out. Check the result before retrying.'],
    ['ETIMEDOUT', 'timeout', 'The request timed out. Check the result before retrying.'],
  ])('explains %s while retaining the original error', (code, kind, message) => {
    const cause = Object.assign(new Error('Technical transport details'), { code });
    const error = normalizeApiError(cause, { message: cause.message, transportMessages });
    expect(error).toMatchObject({ code, kind, message });
    expect(error.cause).toBe(cause);
    expect(cause.message).toBe('Technical transport details');
  });

  it('can localize an existing transport error without changing its identity or handling state', () => {
    const error = normalizeApiError({ code: 'ERR_NETWORK' }, { message: 'Network Error' });
    error.presentation = 'global';
    const localized = normalizeApiError(error, { message: 'Ignored fallback', transportMessages });
    expect(localized).toBe(error);
    expect(localized).toMatchObject({ message: 'Cannot connect. Check your network and try again.', presentation: 'global' });
  });

  it.each([
    { status_code: 26130, status_message: 'Version changed', data: { version: 3 } },
    { response: { status: 409, data: { status_code: 26130, status_message: 'Version changed', data: { version: 3 } } } },
  ])('keeps a specific business explanation instead of a transport fallback', cause => {
    const error = normalizeApiError(cause, { message: 'The version changed. Refresh before saving.', transportMessages });
    expect(error).toMatchObject({ status_code: 26130, data: { version: 3 }, message: 'The version changed. Refresh before saving.' });
  });
});
