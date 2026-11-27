import { JSEncrypt } from 'jsencrypt';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import request, { platformAuth } from '~/api/request';
import { useTranslation } from 'react-i18next';
import { Button } from '~/components/ui/Button';
import { Input } from '~/components/ui/Input';
import { useLocalize } from '~/hooks';

type CaptchaData = { captcha_key: string; user_capthca: boolean; captcha: string };
type ApiEnvelope<T> = { status_code: number; status_message: string; data: T };

async function encryptPwd(raw: string): Promise<string> {
  const resp = await request.get<ApiEnvelope<{ public_key: string }>>(
    '/api/v1/user/public_key',
  );
  const enc = new JSEncrypt();
  enc.setPublicKey(resp.data.public_key);
  return enc.encrypt(raw) as string;
}

export default function DevLogin() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const localize = useLocalize();
  const mailRef = useRef<HTMLInputElement>(null);
  const pwdRef = useRef<HTMLInputElement>(null);
  const captchaRef = useRef<HTMLInputElement>(null);
  const [captcha, setCaptcha] = useState<CaptchaData>({
    captcha_key: '',
    user_capthca: false,
    captcha: '',
  });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string>('');

  const fetchCaptcha = () => {
    request
      .get<ApiEnvelope<CaptchaData>>('/api/v1/user/get_captcha')
      .then((r) => setCaptcha(r.data));
  };

  useEffect(() => {
    fetchCaptcha();
  }, []);

  const submit = async () => {
    setErr('');
    const mail = mailRef.current?.value;
    const pwd = pwdRef.current?.value;
    if (!mail || !pwd) {
      setErr(t('platformAuth.credentialsRequired'));
      return;
    }
    if (captcha.user_capthca && !captchaRef.current?.value) {
      setErr(t('platformAuth.captchaRequired'));
      return;
    }
    setLoading(true);
    try {
      const encrypted = await encryptPwd(pwd);
      await platformAuth.login({
        user_name: mail,
        password: encrypted,
        captcha_key: captcha.captcha_key,
        captcha: captchaRef.current?.value ?? '',
      });
      localStorage.setItem('isLogin', '1');
      navigate('/c/new', { replace: true });
    } catch (e: any) {
      setErr(e?.response?.data?.status_message || e?.message || t('platformAuth.loginFailed'));
      fetchCaptcha();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-4 rounded-xl border bg-surface-primary p-8 shadow-lg">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Dev Login</h1>
          <p className="mt-1 text-xs text-text-secondary">
            Hidden developer entry · backend <code>/api/v1/auth/login</code>
          </p>
        </div>
        <div className="space-y-3">
          <Input
            ref={mailRef}
            type="email"
            placeholder={localize('accountIdentity.account')}
            autoComplete="email"
            onKeyDown={(e) => e.key === 'Enter' && pwdRef.current?.focus()}
          />
          <Input
            ref={pwdRef}
            type="password"
            placeholder={localize('com_auth_password')}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          {captcha.user_capthca && (
            <div className="flex items-center gap-2">
              <Input ref={captchaRef} type="text" placeholder={t('platformAuth.captcha')} />
              <img
                src={`data:image/jpg;base64,${captcha.captcha}`}
                alt="captcha"
                onClick={fetchCaptcha}
                className="h-10 w-[120px] cursor-pointer rounded border"
                title={t('platformAuth.refreshCaptcha')}
              />
            </div>
          )}
          {err && <div className="text-xs text-red-500">{err}</div>}
          <Button
            variant="submit"
            className="w-full"
            disabled={loading}
            onClick={submit}
          >
            {loading ? t('platformAuth.signingIn') : t('platformAuth.signIn')}
          </Button>
        </div>
      </div>
    </div>
  );
}
