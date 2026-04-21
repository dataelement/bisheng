import { JSEncrypt } from 'jsencrypt';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import request from '~/api/request';
import { Button } from '~/components/ui/Button';
import { Input } from '~/components/ui/Input';

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
    const mail = mailRef.current?.value?.trim();
    const pwd = pwdRef.current?.value;
    if (!mail || !pwd) {
      setErr('请输入账号和密码');
      return;
    }
    if (captcha.user_capthca && !captchaRef.current?.value) {
      setErr('请输入验证码');
      return;
    }
    setLoading(true);
    try {
      const encrypted = await encryptPwd(pwd);
      const resp = await request.post('/api/v1/user/login', {
        user_name: mail,
        password: encrypted,
        captcha_key: captcha.captcha_key,
        captcha: captchaRef.current?.value ?? '',
      });
      if (resp?.status_code !== 200) {
        setErr(resp?.status_message || '登录失败');
        fetchCaptcha();
        return;
      }
      // Backend sets HttpOnly access_token cookie on success; browser keeps it.
      // Mirror platform's localStorage flags for cross-app consistency.
      const token = resp?.data?.access_token;
      if (token) {
        localStorage.setItem('ws_token', token);
        window.dispatchEvent(new CustomEvent('tokenUpdated', { detail: token }));
      }
      localStorage.setItem('isLogin', '1');
      navigate('/c/new', { replace: true });
    } catch (e: any) {
      setErr(e?.response?.data?.status_message || e?.message || '登录失败');
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
            Hidden developer entry · backend <code>/api/v1/user/login</code>
          </p>
        </div>
        <div className="space-y-3">
          <Input
            ref={mailRef}
            type="email"
            placeholder="账号 / email"
            autoComplete="email"
            onKeyDown={(e) => e.key === 'Enter' && pwdRef.current?.focus()}
          />
          <Input
            ref={pwdRef}
            type="password"
            placeholder="密码"
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
          {captcha.user_capthca && (
            <div className="flex items-center gap-2">
              <Input ref={captchaRef} type="text" placeholder="验证码" />
              <img
                src={`data:image/jpg;base64,${captcha.captcha}`}
                alt="captcha"
                onClick={fetchCaptcha}
                className="h-10 w-[120px] cursor-pointer rounded border"
                title="点击刷新"
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
            {loading ? '登录中…' : '登录'}
          </Button>
        </div>
      </div>
    </div>
  );
}
