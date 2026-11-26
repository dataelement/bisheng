import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/bs-ui/dialog'
import type {
    OAuth2ClientCreateInput,
    OAuth2ClientItem,
    OAuth2ClientType,
    OAuth2ClientUpdateInput,
} from '@/types/oauth2'
import { Button, Input, Switch, Textarea } from '@bisheng/ui'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

const AVAILABLE_SCOPES = ['openid', 'profile', 'email', 'offline_access', 'dsh']

interface ClientFormDialogProps {
    open: boolean
    editing: OAuth2ClientItem | null
    saving: boolean
    onOpenChange: (open: boolean) => void
    onCreate: (payload: OAuth2ClientCreateInput) => Promise<void>
    onUpdate: (
        clientId: string,
        payload: OAuth2ClientUpdateInput,
    ) => Promise<void>
}

export function ClientFormDialog({
    open,
    editing,
    saving,
    onOpenChange,
    onCreate,
    onUpdate,
}: ClientFormDialogProps) {
    const { t } = useTranslation()
    const [clientId, setClientId] = useState('')
    const [clientName, setClientName] = useState('')
    const [description, setDescription] = useState('')
    const [clientType, setClientType] = useState<OAuth2ClientType>('confidential')
    const [redirectUrisText, setRedirectUrisText] = useState('')
    const [allowLoopbackPort, setAllowLoopbackPort] = useState(false)
    const [scopes, setScopes] = useState<string[]>([
        'openid',
        'profile',
        'email',
        'offline_access',
    ])
    const [requirePkce, setRequirePkce] = useState(true)
    const [requireConsent, setRequireConsent] = useState(true)
    const [enabled, setEnabled] = useState(true)
    const [errorText, setErrorText] = useState<string | null>(null)

    useEffect(() => {
        if (!open) return
        setErrorText(null)
        if (editing) {
            setClientId(editing.client_id)
            setClientName(editing.client_name)
            setDescription(editing.description ?? '')
            setClientType(editing.client_type)
            setRedirectUrisText(editing.redirect_uris.join('\n'))
            setAllowLoopbackPort(editing.allow_loopback_port)
            setScopes(editing.allowed_scopes)
            setRequirePkce(editing.require_pkce)
            setRequireConsent(editing.require_consent)
            setEnabled(editing.enabled)
        } else {
            setClientId('')
            setClientName('')
            setDescription('')
            setClientType('confidential')
            setRedirectUrisText('')
            setAllowLoopbackPort(false)
            setScopes(['openid', 'profile', 'email', 'offline_access'])
            setRequirePkce(true)
            setRequireConsent(true)
            setEnabled(true)
        }
    }, [editing, open])

    function toggleScope(scope: string) {
        setScopes((prev) =>
            prev.includes(scope)
                ? prev.filter((item) => item !== scope)
                : [...prev, scope],
        )
    }

    async function handleSubmit() {
        const trimmedName = clientName.trim()
        const uris = redirectUrisText
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter(Boolean)
        if (!trimmedName || uris.length === 0 || scopes.length === 0) {
            setErrorText(t('oauth2.admin.validationRequired'))
            return
        }
        setErrorText(null)
        if (editing) {
            await onUpdate(editing.client_id, {
                client_name: trimmedName,
                description: description.trim() || null,
                redirect_uris: uris,
                allow_loopback_port: allowLoopbackPort,
                allowed_scopes: scopes,
                require_pkce: clientType === 'public' ? true : requirePkce,
                require_consent: requireConsent,
                enabled,
            })
        } else {
            await onCreate({
                client_id: clientId.trim() || undefined,
                client_name: trimmedName,
                description: description.trim() || null,
                client_type: clientType,
                redirect_uris: uris,
                allow_loopback_port: allowLoopbackPort,
                allowed_scopes: scopes,
                grant_types: ['authorization_code', 'refresh_token'],
                require_pkce: clientType === 'public' ? true : requirePkce,
                require_consent: requireConsent,
                enabled,
                access_token_ttl: 3600,
                refresh_token_ttl: 1209600,
            })
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle>
                        {editing
                            ? t('oauth2.admin.editTitle')
                            : t('oauth2.admin.createTitle')}
                    </DialogTitle>
                </DialogHeader>

                <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto py-1 pr-1">
                    <div className="flex flex-col gap-1.5">
                        <label className="text-sm font-medium">
                            {t('oauth2.admin.clientName')}
                        </label>
                        <Input
                            value={clientName}
                            onChange={(e) => setClientName(e.target.value)}
                            placeholder={t('oauth2.admin.clientNamePlaceholder')}
                        />
                    </div>

                    {!editing && (
                        <>
                            <div className="flex flex-col gap-1.5">
                                <label className="text-sm font-medium">
                                    {t('oauth2.admin.clientIdOptional')}
                                </label>
                                <Input
                                    value={clientId}
                                    onChange={(e) => setClientId(e.target.value)}
                                    placeholder={t(
                                        'oauth2.admin.clientIdPlaceholder',
                                    )}
                                />
                            </div>

                            <div className="flex flex-col gap-1.5">
                                <label className="text-sm font-medium">
                                    {t('oauth2.admin.clientType')}
                                </label>
                                <div className="flex gap-2">
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant={
                                            clientType === 'confidential'
                                                ? 'default'
                                                : 'outline'
                                        }
                                        onClick={() =>
                                            setClientType('confidential')
                                        }
                                    >
                                        {t('oauth2.admin.typeConfidential')}
                                    </Button>
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant={
                                            clientType === 'public'
                                                ? 'default'
                                                : 'outline'
                                        }
                                        onClick={() => {
                                            setClientType('public')
                                            setRequirePkce(true)
                                        }}
                                    >
                                        {t('oauth2.admin.typePublic')}
                                    </Button>
                                </div>
                            </div>
                        </>
                    )}

                    <div className="flex flex-col gap-1.5">
                        <label className="text-sm font-medium">
                            {t('oauth2.admin.description')}
                        </label>
                        <Input
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder={t('oauth2.admin.descriptionPlaceholder')}
                        />
                    </div>

                    <div className="flex flex-col gap-1.5">
                        <label className="text-sm font-medium">
                            {t('oauth2.admin.redirectUris')}
                        </label>
                        <Textarea
                            rows={3}
                            value={redirectUrisText}
                            onChange={(e) =>
                                setRedirectUrisText(e.target.value)
                            }
                            placeholder={t(
                                'oauth2.admin.redirectUrisPlaceholder',
                            )}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <label className="text-sm font-medium">
                            {t('oauth2.admin.scopes')}
                        </label>
                        <div className="flex flex-wrap gap-2">
                            {AVAILABLE_SCOPES.map((scope) => {
                                const active = scopes.includes(scope)
                                return (
                                    <Button
                                        key={scope}
                                        type="button"
                                        size="sm"
                                        variant={active ? 'default' : 'outline'}
                                        onClick={() => toggleScope(scope)}
                                    >
                                        {scope}
                                    </Button>
                                )
                            })}
                        </div>
                    </div>

                    <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
                        <div>
                            <p className="text-sm font-medium">
                                {t('oauth2.admin.requireConsent')}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                {t('oauth2.admin.requireConsentHint')}
                            </p>
                        </div>
                        <Switch
                            checked={requireConsent}
                            onCheckedChange={setRequireConsent}
                        />
                    </div>

                    <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
                        <div>
                            <p className="text-sm font-medium">
                                {t('oauth2.admin.allowLoopbackPort')}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                {t('oauth2.admin.allowLoopbackPortHint')}
                            </p>
                        </div>
                        <Switch
                            checked={allowLoopbackPort}
                            onCheckedChange={setAllowLoopbackPort}
                        />
                    </div>

                    <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
                        <div>
                            <p className="text-sm font-medium">
                                {t('oauth2.admin.requirePkce')}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                {t('oauth2.admin.requirePkceHint')}
                            </p>
                        </div>
                        <Switch
                            checked={clientType === 'public' ? true : requirePkce}
                            disabled={clientType === 'public'}
                            onCheckedChange={setRequirePkce}
                        />
                    </div>

                    <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
                        <p className="text-sm font-medium">
                            {t('oauth2.admin.enabled')}
                        </p>
                        <Switch checked={enabled} onCheckedChange={setEnabled} />
                    </div>

                    {errorText && (
                        <p className="text-sm text-destructive">{errorText}</p>
                    )}
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        disabled={saving}
                        onClick={() => onOpenChange(false)}
                    >
                        {t('cancel')}
                    </Button>
                    <Button
                        disabled={saving}
                        onClick={() => void handleSubmit()}
                    >
                        {t('save')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
