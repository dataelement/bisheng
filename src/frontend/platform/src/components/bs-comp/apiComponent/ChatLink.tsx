// @ts-strict-ignore
import { Alert, Button, Select, notification } from '@bisheng/ui';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';

import { Label } from '@/components/bs-ui/label';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import Skeleton from '@/components/bs-ui/skeleton';
import { Switch } from '@bisheng/ui';

import { getGuestLinkApi, GuestLinkKind, GuestLinkSettings, patchGuestLinkApi } from '@/controllers/API/guestLink';
import { showApiError } from '@/controllers/request';
import { copyText } from '@/utils';
import { Outlined } from 'bisheng-icons';
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
          <Outlined.CloseCircle className='h-6 w-6 text-foreground' />
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
  const [operatorQuery, setOperatorQuery] = useState('')
  const [searchedCandidates, setSearchedCandidates] = useState<GuestLinkSettings['candidates'] | null>(null)
  const [searching, setSearching] = useState(false)
  const selectLabels = useSelectLabels()

  useEffect(() => {
    let cancelled = false
    getGuestLinkApi(kind, appId).then((data) => {
      if (!cancelled && data) {
        setSettings(data)
        onAvailabilityChange(Boolean(data.system_guest_access && data.enabled))
      }
    }).catch(showApiError)
    return () => {
      cancelled = true
    }
  }, [kind, appId, onAvailabilityChange])

  useEffect(() => {
    const keyword = operatorQuery.trim()
    if (!keyword) {
      setSearchedCandidates(null)
      setSearching(false)
      return
    }
    // The shared Select already debounces onSearch (300ms), so query right away.
    let cancelled = false
    setSearching(true)
    getGuestLinkApi(kind, appId, keyword).then((data) => {
      if (cancelled) return
      setSearching(false)
      if (data) {
        setSearchedCandidates(data.candidates || [])
      }
    }).catch(showApiError).finally(() => { if (!cancelled) setSearching(false) })
    return () => {
      cancelled = true
    }
  }, [kind, appId, operatorQuery])

  const persist = async (patch: { enabled?: boolean; user_id?: number | null }, previous: GuestLinkSettings) => {
    setSaving(true)
    try {
    const result = await patchGuestLinkApi(kind, appId, patch)
    setSettings(result)
    onAvailabilityChange(Boolean(result.system_guest_access && result.enabled))
    notification.open({ type: 'success', description: String(t('api.guestSaved') ?? '') })
    } catch (error) {
      setSettings(previous)
      onAvailabilityChange(Boolean(previous.system_guest_access && previous.enabled))
      showApiError(error)
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return <Skeleton className="mb-4 h-24 w-full rounded" />
  }

  const systemOff = !settings.system_guest_access
  const readOnly = !settings.can_edit || systemOff || saving
  const controlsOff = systemOff || !settings.enabled
  const candidates = (searchedCandidates ?? settings.candidates ?? []).filter((item) => item?.user_id)
  const selectValue = settings.operator_user_id ? String(settings.operator_user_id) : undefined
  const keyword = operatorQuery.trim().toLowerCase()
  const visibleCandidates = keyword
    ? candidates.filter((item) => {
        const name = String(item.user_name || '').toLowerCase()
        return name.includes(keyword) || String(item.user_id) === selectValue
      })
    : candidates
  // Keep the current operator among the options so the trigger can still name it
  // while a server search returns a list without them.
  const selectedCandidate = selectValue
    ? (settings.candidates ?? []).find((item) => String(item?.user_id) === selectValue)
    : undefined
  const optionCandidates = selectedCandidate && !visibleCandidates.some((item) => String(item.user_id) === selectValue)
    ? [selectedCandidate, ...visibleCandidates]
    : visibleCandidates
  const operatorOptions = optionCandidates.map((item) => ({
    value: String(item.user_id),
    label: `${item.user_name ?? ''}${settings.follow_system_default && item.user_id === settings.default_operator_user_id
      ? ` · ${t('api.systemDefault')}`
      : ''}`,
  }))
  const warningMessages = [
    settings.warnings?.operator_is_admin ? t('api.guestWarnAdmin') : null,
    settings.warnings?.default_not_in_tenant ? t('api.guestWarnDefaultNotInTenant') : null,
    settings.warnings?.operator_inactive ? t('api.guestWarnOperatorInactive') : null,
  ].filter((message): message is string => typeof message === 'string' && message.length > 0)

  return (
    <>
      <Alert
        type={systemOff ? 'error' : 'info'}
        className="mb-4"
        description={String(systemOff ? t('api.guestAccessDisabledSystem') : t('api.noLoginLinkDescription'))}
      />

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
              {...selectLabels}
              aria-label={t('api.guestOperator')}
              className="max-w-sm"
              showSearch
              placeholder={t('api.guestSelectOperator')}
              noMatchText={t('api.guestOperatorNotFound')}
              emptyText={t('api.guestOperatorNotFound')}
              options={operatorOptions}
              loading={searching}
              onSearch={setOperatorQuery}
              value={selectValue ?? null}
              disabled={readOnly}
              onChange={(value) => {
                if (value == null || String(value) === selectValue) return
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
            />
            {settings.follow_system_default && (
              <span className="text-xs text-muted-foreground">{t('api.systemDefault')}</span>
            )}
            {!settings.follow_system_default && settings.can_edit && !systemOff && (
              <Button type="button" variant="link" size="small" disabled={saving} onClick={() => {
                  const previous = settings
                  setSettings({ ...settings, follow_system_default: true, user_id: null })
                  void persist({ user_id: null }, previous)
                }}>
                {t('api.restoreSystemDefault')}
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{t('api.guestOperatorHint')}</p>
          {warningMessages.length > 0 && (
            <Alert
              type="warning"
              description={warningMessages.join(' ')}
            />
          )}
        </div>
      )}

      {controlsOff && !systemOff && (
        <Alert className="mb-4" description={String(t('api.guestLinkDisabled'))} />
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
  }, [type, noLogin, id])

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
        <Alert
          className="mb-4"
          description={String(noLogin
              ? t('api.noLoginLinkDescription')
              : t('api.loginLinkDescription'))}
        />
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
                {isCopied ? <Outlined.Check size={18} /> : <Outlined.Copy size={15} />}
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
                {isCopied ? <Outlined.Check size={18} /> : <Outlined.Copy size={15} />}
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
