// @ts-strict-ignore
import { Alert, AlertDescription } from '@/components/bs-ui/alert';
import { Button } from '@/components/bs-ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Label } from '@/components/bs-ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import Skeleton from '@/components/bs-ui/skeleton';
import { Switch } from '@/components/bs-ui/switch';
import { toast } from '@/components/bs-ui/toast/use-toast';
import { getGuestLinkApi, GuestLinkKind, GuestLinkSettings, patchGuestLinkApi } from '@/controllers/API/guestLink';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { copyText } from '@/utils';
import { Check, CircleX, Clipboard, Info } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";

const BorwserSkeleton = ({ size = '' }) => {
  return <div className="p-4 rounded-lg max-w-lg mx-auto">
    {/* 浏览器窗口的骨架 */}
    <div className="border border-border rounded-lg overflow-hidden">
      {/* 浏览器顶部导航栏骨架 */}
      <div className="p-2 bg-accent flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Skeleton className="h-4 w-4 rounded-full" /> {/* 浏览器左上角圆形图标 */}
          <Skeleton className="h-4 w-4 rounded-full" />
          <Skeleton className="h-4 w-4 rounded-full" />
        </div>
        <Skeleton className="h-4 w-1/2 rounded" /> {/* 浏览器地址栏骨架 */}
        <Skeleton className="h-4 w-4 rounded" /> {/* 浏览器右上角按钮 */}
      </div>

      {/* 聊天窗口的骨架 */}
      {
        size ? <div className="p-4 bg-white flex justify-end items-end">
          <div className="border w-[200px] rounded-lg p-4 space-y-4">
            <Skeleton className="h-4 w-3/4 rounded" /> {/* 聊天标题 */}
            <Skeleton className="h-44 w-full rounded" /> {/* 聊天内容区域 */}
            <div className="flex items-center">
              <Skeleton className="h-6 w-full rounded" /> {/* 输入框骨架 */}
              <Skeleton className="h-6 w-16 ml-2 rounded" /> {/* 发送按钮骨架 */}
            </div>
          </div>
          <CircleX className='h-6 w-6 text-foreground' />
        </div>
          : <div className="p-4 bg-white">
            <div className="border border-border rounded-lg p-4 space-y-4">
              <Skeleton className="h-6 w-3/4 rounded" /> {/* 聊天标题 */}
              <Skeleton className="h-40 w-full rounded" /> {/* 聊天内容区域 */}
              <div className="flex items-center">
                <Skeleton className="h-8 w-full rounded" /> {/* 输入框骨架 */}
                <Skeleton className="h-8 w-16 ml-2 rounded" /> {/* 发送按钮骨架 */}
              </div>
            </div>
          </div>
      }
    </div>
  </div>
}

const enum API_TYPE {
  ASSISTANT = 'assistant',
  SKILL = 'skill',
  FLOW = 'flow'
}

function guestLinkKind(type: string): GuestLinkKind | null {
  if (type === API_TYPE.FLOW) return 'workflow'
  if (type === API_TYPE.ASSISTANT) return 'assistant'
  return null
}

interface GuestLinkPanelProps {
  kind: GuestLinkKind
  appId: string
  onAvailabilityChange: (available: boolean) => void
}

function GuestLinkPanel({ kind, appId, onAvailabilityChange }: GuestLinkPanelProps) {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<GuestLinkSettings | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    captureAndAlertRequestErrorHoc(getGuestLinkApi(kind, appId)).then((data) => {
      if (!cancelled && data) {
        setSettings(data)
        onAvailabilityChange(Boolean(data.system_guest_access && data.enabled))
      }
    })
    return () => {
      cancelled = true
    }
  }, [kind, appId])

  const persist = async (patch: { enabled?: boolean; user_id?: number | null }, previous: GuestLinkSettings) => {
    setSaving(true)
    const result = await captureAndAlertRequestErrorHoc(patchGuestLinkApi(kind, appId, patch))
    setSaving(false)
    if (result === false || !result) {
      setSettings(previous)
      onAvailabilityChange(Boolean(previous.system_guest_access && previous.enabled))
      return
    }
    setSettings(result)
    onAvailabilityChange(Boolean(result.system_guest_access && result.enabled))
    toast({ variant: 'success', description: t('api.guestSaved') })
  }

  if (!settings) {
    return <Skeleton className="mb-4 h-24 w-full rounded" />
  }

  const systemOff = !settings.system_guest_access
  const readOnly = !settings.can_edit || systemOff || saving
  const controlsOff = systemOff || !settings.enabled
  const candidates = (settings.candidates || []).filter((item) => item?.user_id)
  const selectValue = settings.operator_user_id ? String(settings.operator_user_id) : undefined

  return (
    <>
      <Alert className="mb-4">
        <Info className="h-4 w-4" />
        <AlertDescription className="mt-0.5">
          {systemOff ? t('api.guestAccessDisabledSystem') : t('api.noLoginLinkDescription')}
        </AlertDescription>
      </Alert>

      <div className="mb-6 flex items-center justify-between gap-4">
        <Label htmlFor="guest-link-enabled">{t('api.allowGuestAccess')}</Label>
        <Switch
          id="guest-link-enabled"
          checked={settings.enabled}
          disabled={readOnly}
          onCheckedChange={(next) => {
            const previous = settings
            setSettings({ ...settings, enabled: next })
            onAvailabilityChange(Boolean(settings.system_guest_access && next))
            void persist({ enabled: next }, previous)
          }}
        />
      </div>

      {settings.enabled && (
        <div className={`mb-6 space-y-3 ${systemOff ? 'pointer-events-none opacity-50' : ''}`}>
          <div className="flex items-center gap-3">
            <Label className="shrink-0">{t('api.guestOperator')}</Label>
            <Select
              value={selectValue}
              disabled={readOnly}
              onValueChange={(value) => {
                if (!value) return
                const previous = settings
                const userId = Number(value)
                setSettings({
                  ...settings,
                  follow_system_default: false,
                  user_id: userId,
                  operator_user_id: userId,
                })
                void persist({ user_id: userId }, previous)
              }}
            >
              <SelectTrigger className="max-w-sm">
                <SelectValue placeholder={t('api.guestSelectOperator')} />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((item) => (
                  <SelectItem key={item.user_id} value={String(item.user_id)}>
                    {item.user_name}
                    {settings.follow_system_default && item.user_id === settings.default_operator_user_id
                      ? ` · ${t('api.systemDefault')}`
                      : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {settings.follow_system_default && (
              <span className="text-xs text-muted-foreground">{t('api.systemDefault')}</span>
            )}
            {!settings.follow_system_default && settings.can_edit && !systemOff && (
              <Button
                type="button"
                variant="link"
                size="sm"
                disabled={saving}
                onClick={() => {
                  const previous = settings
                  setSettings({ ...settings, follow_system_default: true, user_id: null })
                  void persist({ user_id: null }, previous)
                }}
              >
                {t('api.restoreSystemDefault')}
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{t('api.guestOperatorHint')}</p>
          {settings.warnings?.operator_is_admin && (
            <Alert className="border-orange-300 text-orange-800">
              <AlertDescription>{t('api.guestWarnAdmin')}</AlertDescription>
            </Alert>
          )}
          {settings.warnings?.default_not_in_tenant && (
            <Alert className="border-orange-300 text-orange-800">
              <AlertDescription>{t('api.guestWarnDefaultNotInTenant')}</AlertDescription>
            </Alert>
          )}
          {settings.warnings?.operator_inactive && (
            <Alert className="border-orange-300 text-orange-800">
              <AlertDescription>{t('api.guestWarnOperatorInactive')}</AlertDescription>
            </Alert>
          )}
        </div>
      )}

      {controlsOff && !systemOff && (
        <Alert className="mb-4">
          <AlertDescription>{t('api.guestLinkDisabled')}</AlertDescription>
        </Alert>
      )}
    </>
  )
}

const NoLoginLink = ({ type, noLogin = false }) => {
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const { t } = useTranslation()
  const { id } = useParams()
  const [guestAvailable, setGuestAvailable] = useState(true)
  const kind = guestLinkKind(type)

  const copyToClipboard = (code: string) => {
    if (noLogin && !guestAvailable) return
    setIsCopied(true);
    copyText(code).then(() => {
      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    })
  }

  const [embed, setEmbed] = useState(false)
  const url = useMemo(() => {
    const loginUrl = `${location.origin}${__APP_ENV__.BASE_URL}/workspace/chat/${type}/auth/${id}`
    const noLoginUrl = `${location.origin}${__APP_ENV__.BASE_URL}/workspace/chat/${type === API_TYPE.SKILL ? '' : type + '/'}${id}`
    return noLogin ? noLoginUrl : loginUrl;
  }, [type, noLogin])

  const embedCode = useMemo(() => {
    if (embed) return `<script
  src="${location.origin}/iframe.js"
  id="chatbot-iframe-script"
  data-bot-src="${url}"
  data-drag="true"
  data-open-icon="${location.origin}/assets/user.png"
  data-close-icon="${location.origin}/logo-small-dark.png"
  defer
></script>
<script>console.log("chat ready")</script>
`

    return `<iframe
  src="${url}"
  style="width: 100%; height: 100%; min-height: 700px"
  frameborder="0"
  allow="fullscreen;clipboard-write">
</iframe>`
  }, [embed, url])

  return (
    <section className='pb-20 max-w-[1600px]'>
      {noLogin && kind && id ? (
        <GuestLinkPanel kind={kind} appId={String(id)} onAvailabilityChange={setGuestAvailable} />
      ) : (
        <Alert className='mb-4'>
          <Info className="h-4 w-4" />
          <AlertDescription className='mt-0.5'>
            {noLogin
              ? t('api.noLoginLinkDescription')
              : t('api.loginLinkDescription')}
          </AlertDescription>
        </Alert>
      )}

      <div className={noLogin && !guestAvailable ? 'pointer-events-none opacity-50' : undefined}>
      <h3 className="text-lg font-bold mt-8 mb-2">{t('api.publishAsStandalonePage')}</h3>
      <Card className='mb-4'>
        <CardHeader className='pt-2 pb-0'>
          <CardTitle className='flex justify-between items-center'>
            <p>{t('api.copyLinkToBrowser')}</p>
            <div>
              <button
                className="flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                onClick={() => copyToClipboard(url)}
              >
                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
              </button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SyntaxHighlighter
            className="w-full overflow-auto custom-scroll"
            language={'javascript'}
            style={oneDark}
          >
            {url}
          </SyntaxHighlighter>
        </CardContent>
      </Card>

      <h3 className="text-lg font-bold mt-8 mb-2">{t('api.embedIntoWebsite')}</h3>
      <div className='flex gap-2 mb-4'>
        <Card className={`w-1/2 dark:bg-[#111] cursor-pointer border-2 ${embed ? '' : 'border-primary hover:border-primary dark:hover:border-primary'}`} onClick={() => setEmbed(false)}>
          <CardHeader className='pt-2 pb-0'>
            <CardTitle>{t('api.styleOne')}</CardTitle>
          </CardHeader>
          <CardContent>
            <BorwserSkeleton />
          </CardContent>
        </Card>
        <Card className={`w-1/2 dark:bg-[#111] cursor-pointer border-2 ${embed ? 'border-primary hover:border-primary dark:hover:border-primary' : ''}`} onClick={() => setEmbed(true)}>
          <CardHeader className='pt-2 pb-0'>
            <CardTitle>{t('api.styleTwo')}</CardTitle>
          </CardHeader>
          <CardContent>
            <BorwserSkeleton size='small' />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className='pt-2 pb-0'>
          <CardTitle className='flex justify-between items-center'>
            <p>{t('api.embedCodeDescription')}</p>
            <div>
              <button
                className="flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                onClick={() => copyToClipboard(embedCode)}
              >
                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
              </button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SyntaxHighlighter
            className="w-full overflow-auto custom-scroll"
            language={'javascript'}
            style={oneDark}
          >
            {embedCode}
          </SyntaxHighlighter>
        </CardContent>
      </Card>
      </div>
    </section>
  );
};

export default NoLoginLink;
