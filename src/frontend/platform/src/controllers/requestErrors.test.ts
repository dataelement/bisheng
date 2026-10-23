import { afterEach, describe, expect, it, vi } from 'vitest';
import request, { showApiError, captureAndAlertRequestErrorHoc, handleUiRequest } from './request';
import { ApiError } from '@bisheng/api-client';

const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
const adapter = request.defaults.adapter;
afterEach(() => { request.defaults.adapter = adapter; notices.mockClear(); vi.restoreAllMocks(); });

describe('platform structured failure contract', () => {
  it('retains business failure and presents it once across layers', async () => {
    request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 26130, status_message: 'Conflict', data: { version: 2 } } });
    const error = await request.get('/test').catch(cause => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status_code: 26130, httpStatus: 200, data: { version: 2 } });
    showApiError(error);
    showApiError(error);
    expect(notices).toHaveBeenCalledTimes(1);
  });

  it('retains a transport failure after the shared notification', async () => {
    const response = { status: 409, data: { status_code: 26130, status_message: 'Conflict' } };
    const original = Object.assign(new Error('HTTP 409'), { response });
    request.defaults.adapter = async config => { throw Object.assign(original, { config }); };
    const error = await request.get('/test').catch(cause => cause);
    expect(error).toMatchObject({ status_code: 26130, httpStatus: 409, presentation: 'toast' });
    expect(error.response).toBe(response);
    expect(error.cause).toBe(original);
    showApiError(error);
    expect(notices).toHaveBeenCalledTimes(1);
  });

  it('keeps silent failures inspectable without notifying', async () => {
    request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 11055, status_message: 'duplicate', data: { skill_id: 8 } } });
    const error = await request.get('/test', { silent: true }).catch(cause => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.data).toEqual({ skill_id: 8 });
    expect(notices).not.toHaveBeenCalled();
  });

  it('preserves successful non-envelope responses and binary downloads', async () => {
    const data = { valid: true };
    request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data });
    expect(await request.get('/test')).toEqual(data);
    const blob = new Blob(['pdf'], { type: 'application/pdf' });
    request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: blob });
    expect(await request.get('/test')).toBe(blob);
  });
});

it('keeps rejection visible through the legacy notice helper', async () => {
  const error = new ApiError({ status_code: 26130 }, { message: 'conflict' });
  await expect(captureAndAlertRequestErrorHoc(Promise.reject(error))).rejects.toBe(error);
  expect(notices).toHaveBeenCalledTimes(1);
});

it('consumes failure only at the UI event boundary, without running success actions', async () => {
  let continued = false;
  let pending = true;
  const failure = new ApiError({ status_code: 26130 }, { message: 'conflict' });
  const click = handleUiRequest(async () => {
    try {
      await Promise.reject(failure);
      continued = true;
    } finally { pending = false; }
  });
  expect(click()).toBeUndefined();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(continued).toBe(false);
  expect(pending).toBe(false);
  expect(notices).toHaveBeenCalledTimes(1);
});
