import { dshLaunchUrl, parseDshLaunchBase } from './dshLaunch';

it('preserves the existing client protocol and adds exactly the platform origin', () => {
  const url = new URL(dshLaunchUrl());
  expect(url.protocol).toBe('dsh-desktop:');
  expect(url.hostname).toBe('login');
  expect([...url.searchParams.entries()]).toEqual([['server', window.location.origin]]);
});
it('uses a configured native protocol destination', () => {
  const url = new URL(dshLaunchUrl('dsh-desktop-test://login'));
  expect(url.protocol).toBe('dsh-desktop-test:');
  expect(url.searchParams.get('server')).toBe(window.location.origin);
});
it.each(['javascript://alert', 'data://text', 'file://host/path', 'https://site.test', 'dsh-desktop://login?server=evil', 'dsh-desktop://login#evil', 'dsh-desktop://user:pass@login', '', null])('rejects unsafe or non-base launch URLs: %s', (value) => {
  expect(() => parseDshLaunchBase(value)).toThrow();
});
