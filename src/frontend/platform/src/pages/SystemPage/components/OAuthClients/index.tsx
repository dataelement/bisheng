import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/bs-ui/dialog'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/bs-ui/table'
import {
    createOAuth2Client,
    deleteOAuth2Client,
    listOAuth2Clients,
    rotateOAuth2ClientSecret,
    updateOAuth2Client,
} from '@/controllers/API/oauth2'
import type {
    OAuth2ClientCreateInput,
    OAuth2ClientItem,
    OAuth2ClientUpdateInput,
} from '@/types/oauth2'
import { copyText } from '@/utils'
import { Button, Switch } from '@bisheng/ui'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ClientFormDialog } from './ClientFormDialog'

export function OAuthClients() {
    const { t } = useTranslation()
    const [clients, setClients] = useState<OAuth2ClientItem[]>([])
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [dialogOpen, setDialogOpen] = useState(false)
    const [editing, setEditing] = useState<OAuth2ClientItem | null>(null)
    const [revealedSecret, setRevealedSecret] = useState<{
        clientId: string
        secret: string
    } | null>(null)
    const [copiedKey, setCopiedKey] = useState<string | null>(null)

    const loadClients = useCallback(async () => {
        setLoading(true)
        try {
            const res = await listOAuth2Clients({ page: 1, page_size: 100 })
            setClients(res.data ?? [])
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void loadClients()
    }, [loadClients])

    async function handleCopy(key: string, value: string) {
        await copyText(value)
        setCopiedKey(key)
        window.setTimeout(() => {
            setCopiedKey((current) => (current === key ? null : current))
        }, 1800)
    }

    async function handleCreate(payload: OAuth2ClientCreateInput) {
        setSaving(true)
        try {
            const result = await createOAuth2Client(payload)
            setDialogOpen(false)
            await loadClients()
            if (result.client_secret) {
                setRevealedSecret({
                    clientId: result.client.client_id,
                    secret: result.client_secret,
                })
            }
        } finally {
            setSaving(false)
        }
    }

    async function handleUpdate(
        clientId: string,
        payload: OAuth2ClientUpdateInput,
    ) {
        setSaving(true)
        try {
            await updateOAuth2Client(clientId, payload)
            setDialogOpen(false)
            setEditing(null)
            await loadClients()
        } finally {
            setSaving(false)
        }
    }

    async function handleToggleEnabled(item: OAuth2ClientItem, checked: boolean) {
        await updateOAuth2Client(item.client_id, { enabled: checked })
        await loadClients()
    }

    async function handleRotateSecret(clientId: string) {
        const result = await rotateOAuth2ClientSecret(clientId)
        if (result.client_secret) {
            setRevealedSecret({
                clientId: result.client.client_id,
                secret: result.client_secret,
            })
        }
    }

    async function handleDelete(clientId: string) {
        await deleteOAuth2Client(clientId)
        await loadClients()
    }

    const discoveryUrl = `${location.origin}/.well-known/oauth-authorization-server`

    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto pb-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 p-4">
                <div className="flex flex-col gap-1">
                    <h2 className="text-base font-semibold">
                        {t('oauth2.admin.title')}
                    </h2>
                    <p className="text-xs text-muted-foreground">
                        {t('oauth2.admin.subtitle')}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>{t('oauth2.admin.discoveryLabel')}:</span>
                        <code className="rounded bg-muted px-2 py-0.5 font-mono text-foreground">
                            {discoveryUrl}
                        </code>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                                void handleCopy('discovery', discoveryUrl)
                            }
                        >
                            {copiedKey === 'discovery'
                                ? t('oauth2.admin.copied')
                                : t('oauth2.admin.copy')}
                        </Button>
                    </div>
                </div>
                <Button
                    onClick={() => {
                        setEditing(null)
                        setDialogOpen(true)
                    }}
                >
                    {t('oauth2.admin.createButton')}
                </Button>
            </div>

            <div className="rounded-xl border">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('oauth2.admin.clientName')}</TableHead>
                            <TableHead>{t('oauth2.admin.clientId')}</TableHead>
                            <TableHead>{t('oauth2.admin.clientType')}</TableHead>
                            <TableHead>
                                {t('oauth2.admin.requireConsent')}
                            </TableHead>
                            <TableHead>{t('oauth2.admin.enabled')}</TableHead>
                            <TableHead className="text-right">
                                {t('oauth2.admin.actions')}
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading ? (
                            <TableRow>
                                <TableCell
                                    colSpan={6}
                                    className="py-8 text-center text-sm text-muted-foreground"
                                >
                                    {t('oauth2.admin.loading')}
                                </TableCell>
                            </TableRow>
                        ) : clients.length === 0 ? (
                            <TableRow>
                                <TableCell
                                    colSpan={6}
                                    className="py-8 text-center text-sm text-muted-foreground"
                                >
                                    {t('oauth2.admin.empty')}
                                </TableCell>
                            </TableRow>
                        ) : (
                            clients.map((item) => (
                                <TableRow key={item.client_id}>
                                    <TableCell className="font-medium">
                                        <div className="flex items-center gap-2">
                                            <span>{item.client_name}</span>
                                            {item.is_builtin && (
                                                <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                                                    {t('oauth2.admin.builtin')}
                                                </span>
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-2">
                                            <code className="font-mono text-xs">
                                                {item.client_id}
                                            </code>
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                onClick={() =>
                                                    void handleCopy(
                                                        item.client_id,
                                                        item.client_id,
                                                    )
                                                }
                                            >
                                                {copiedKey === item.client_id
                                                    ? t('oauth2.admin.copied')
                                                    : t('oauth2.admin.copy')}
                                            </Button>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium">
                                            {item.client_type === 'public'
                                                ? t('oauth2.admin.typePublic')
                                                : t(
                                                      'oauth2.admin.typeConfidential',
                                                  )}
                                        </span>
                                    </TableCell>
                                    <TableCell>
                                        {item.require_consent
                                            ? t('oauth2.admin.consentRequired')
                                            : t('oauth2.admin.consentSilent')}
                                    </TableCell>
                                    <TableCell>
                                        <Switch
                                            checked={item.enabled}
                                            onCheckedChange={(checked) =>
                                                void handleToggleEnabled(
                                                    item,
                                                    checked,
                                                )
                                            }
                                        />
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <div className="flex justify-end gap-2">
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                onClick={() => {
                                                    setEditing(item)
                                                    setDialogOpen(true)
                                                }}
                                            >
                                                {t('edit')}
                                            </Button>
                                            {item.client_type ===
                                                'confidential' && (
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() =>
                                                        void handleRotateSecret(
                                                            item.client_id,
                                                        )
                                                    }
                                                >
                                                    {t(
                                                        'oauth2.admin.rotateSecret',
                                                    )}
                                                </Button>
                                            )}
                                            {!item.is_builtin && (
                                                <Button
                                                    size="sm"
                                                    variant="destructive"
                                                    onClick={() =>
                                                        void handleDelete(
                                                            item.client_id,
                                                        )
                                                    }
                                                >
                                                    {t('delete')}
                                                </Button>
                                            )}
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            <ClientFormDialog
                open={dialogOpen}
                editing={editing}
                saving={saving}
                onOpenChange={setDialogOpen}
                onCreate={handleCreate}
                onUpdate={handleUpdate}
            />

            <Dialog
                open={!!revealedSecret}
                onOpenChange={(open) => {
                    if (!open) setRevealedSecret(null)
                }}
            >
                <DialogContent className="max-w-md">
                    <DialogHeader>
                        <DialogTitle>
                            {t('oauth2.admin.secretModalTitle')}
                        </DialogTitle>
                    </DialogHeader>
                    <p className="text-sm text-muted-foreground">
                        {t('oauth2.admin.secretModalWarning')}
                    </p>
                    {revealedSecret && (
                        <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3">
                            <p className="text-xs text-muted-foreground">
                                Client ID:{' '}
                                <code className="font-mono text-foreground">
                                    {revealedSecret.clientId}
                                </code>
                            </p>
                            <code className="break-all font-mono text-xs text-foreground">
                                {revealedSecret.secret}
                            </code>
                        </div>
                    )}
                    <DialogFooter>
                        {revealedSecret && (
                            <Button
                                variant="outline"
                                onClick={() =>
                                    void handleCopy(
                                        'secret',
                                        revealedSecret.secret,
                                    )
                                }
                            >
                                {copiedKey === 'secret'
                                    ? t('oauth2.admin.copied')
                                    : t('oauth2.admin.copySecret')}
                            </Button>
                        )}
                        <Button onClick={() => setRevealedSecret(null)}>
                            {t('oauth2.admin.done')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
