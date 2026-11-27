import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { LoginPage } from './login';
const mocks = vi.hoisted(() => ({ login: vi.fn(), captcha: vi.fn(), encrypt: vi.fn(), navigate: vi.fn(), returnTo: vi.fn(), toast: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ loginApi: mocks.login, getCaptchaApi: mocks.captcha }));
vi.mock('@/controllers/API/pro', () => ({ getSSOurlApi: () => Promise.resolve({}), ldapLoginApi: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn(), platformAuth: { initialize: vi.fn() } }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { isPro: false, register: false } }) }));
vi.mock('@/utils/loginReturnTo', () => ({ consumeLoginReturnTo: mocks.returnTo }));
vi.mock('@/utils/workspaceUrl', () => ({ getWorkspaceClientUrl: () => '/workspace/' }));
vi.mock('./utils', () => ({ handleEncrypt: mocks.encrypt, handleLdapEncrypt: mocks.encrypt }));
vi.mock('./loginBridge', () => ({ default: () => null }));
vi.mock('./RegistrationForm', () => ({ RegistrationForm: () => null }));
vi.mock('react-router-dom', async () => ({ ...await vi.importActual('react-router-dom'), useNavigate: () => mocks.navigate }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
vi.mock('@bisheng/ui', async () => ({ ...await vi.importActual('@bisheng/ui'), toast: { show: mocks.toast } }));
const target = { href: '', origin: 'http://localhost', pathname: '/', search: '' };
beforeEach(() => {
  vi.clearAllMocks();
  target.href = '';
  vi.stubGlobal('location', target);
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  mocks.captcha.mockResolvedValue({ captcha_key: 'captcha', user_capthca: false });
  mocks.encrypt.mockResolvedValue('encrypted');
  mocks.login.mockResolvedValue({ default_entry: '/workspace' });
  mocks.returnTo.mockReturnValue(null);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function fill() {
  render(<MemoryRouter><LoginPage forceLocal /></MemoryRouter>);
  const account = await screen.findByPlaceholderText('login.account');
  fireEvent.change(account, { target: { value: 'person' } });
  fireEvent.change(screen.getByPlaceholderText('login.password'), { target: { value: 'password' } });
}
it('submits encrypted credentials and preserves a workspace default without storing tokens', async () => {
  await fill();
  localStorage.setItem('theme', 'dark');
  fireEvent.click(screen.getByRole('button', { name: 'login.loginButton' }));
  await waitFor(() => expect(target.href).toBe('/workspace/'));
  expect(mocks.login).toHaveBeenCalledWith('person', 'encrypted', 'captcha', undefined);
  expect(localStorage.getItem('ws_token')).toBeNull();
  expect(localStorage.getItem('theme')).toBe('dark');
});
it('requires the displayed captcha before sending a login request', async () => {
  mocks.captcha.mockResolvedValue({ captcha_key: 'captcha', user_capthca: true });
  await fill();
  await screen.findByPlaceholderText('login.pleaseEnterCaptcha');
  fireEvent.click(screen.getByRole('button', { name: 'login.loginButton' }));
  expect(mocks.toast).toHaveBeenCalled();
  expect(mocks.login).not.toHaveBeenCalled();
});
it('keeps password-expiry navigation owned by the login form', async () => {
  mocks.login.mockRejectedValue({ status_code: 10601 });
  await fill();
  fireEvent.click(screen.getByRole('button', { name: 'login.loginButton' }));
  await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/reset', { state: { noback: true } }));
});
it('uses the validated shared return target after login', async () => {
  mocks.returnTo.mockReturnValue('/workspace/c/return');
  await fill();
  fireEvent.click(screen.getByRole('button', { name: 'login.loginButton' }));
  await waitFor(() => expect(target.href).toBe('/workspace/c/return'));
});
