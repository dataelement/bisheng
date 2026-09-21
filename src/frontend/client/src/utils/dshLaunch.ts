export const DEFAULT_DSH_LAUNCH_URL = 'dsh-desktop://login';

export function parseDshLaunchBase(value: unknown = DEFAULT_DSH_LAUNCH_URL): string {
  if (typeof value !== 'string' || !/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[a-zA-Z0-9][a-zA-Z0-9._~/-]*$/.test(value)) {
    throw new Error('Invalid DSH launch URL');
  }
  const url = new URL(value);
  if (['http:', 'https:', 'ftp:', 'ftps:', 'file:', 'javascript:', 'data:', 'vbscript:', 'blob:', 'about:'].includes(url.protocol)) {
    throw new Error('Invalid DSH launch protocol');
  }
  return value;
}

export function dshLaunchUrl(base: string = DEFAULT_DSH_LAUNCH_URL): string {
  const url = new URL(parseDshLaunchBase(base));
  url.searchParams.set('server', window.location.origin);
  return url.toString();
}
