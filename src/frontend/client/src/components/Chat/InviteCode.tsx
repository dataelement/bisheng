import { useState } from "react";
import { bindInviteCode } from "~/api/linsight";
import { useGetBsConfig, useGetUserLinsightCountQuery } from "~/hooks/queries/data-provider";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { Button, Dialog, DialogContent, DialogDescription, DialogTitle, Input } from "../ui";

interface InvitationCodeFormProps {
    showCode: boolean;
    setShowCode: (open: boolean) => void;
}

export default function InvitationCodeForm({ showCode, setShowCode }: InvitationCodeFormProps) {
    const [invitationCode, setInvitationCode] = useState("")
    const [error, setError] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const { refetch } = useGetUserLinsightCountQuery()
    const { showToast } = useToastContext();
    const { data: bsConfig } = useGetBsConfig()
    const localize = useLocalize()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()

        if (!invitationCode.trim()) {
            setError(localize('com_invite_please_input_code'))
            return
        }

        setIsLoading(true)
        setError("")

        try {
            const result = await bindInviteCode(invitationCode.trim())
            refetch()
            setInvitationCode("")
            setError("")
            setShowCode(false)
            showToast({ message: result.status_message, status: 'success' });
        } catch (err) {
            const message = err instanceof Error && err.message.trim()
                ? err.message
                : localize('com_invite_network_error')
            setError(message)
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <Dialog open={showCode} onOpenChange={setShowCode}>
            <DialogContent className="gap-0 overflow-hidden border-0 p-0 sm:max-w-[520px] sm:rounded-2xl">
                <div className="relative px-8 pb-8 pt-16">
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-x-0 top-0 h-40 overflow-hidden"
                        style={{
                            backgroundImage: 'radial-gradient(circle, rgb(var(--text-4) / 0.55) 0.7px, transparent 0.8px)',
                            backgroundSize: '6px 6px',
                            WebkitMaskImage: 'linear-gradient(to bottom, black 35%, transparent)',
                            maskImage: 'linear-gradient(to bottom, black 35%, transparent)',
                        }}
                    >
                        <div className="absolute inset-x-0 top-1 text-center text-[68px] font-bold leading-none tracking-[0.12em] text-text-4/20">
                            LINSIGHT
                        </div>
                    </div>
                    <DialogTitle className="relative text-h3 font-bold text-primary">
                        {localize('com_invite_title')}
                    </DialogTitle>
                    <DialogDescription className="relative mt-3 text-body text-text-1">
                        {localize('com_invite_desc')}
                    </DialogDescription>
                    <form onSubmit={handleSubmit} className="relative mt-8">
                        <div className="flex items-center gap-3">
                            <Input
                                type="text"
                                size="large"
                                className="min-w-0 flex-1"
                                value={invitationCode}
                                onChange={(e) => setInvitationCode(e.target.value)}
                                placeholder={localize('com_invite_placeholder')}
                                maxLength={50}
                                disabled={isLoading}
                                status={error ? 'error' : undefined}
                            />
                            <Button
                                type="submit"
                                size="large"
                                className="shrink-0 px-8"
                                disabled={isLoading}
                            >
                                {isLoading ? localize('com_invite_submitting') : localize('com_invite_submit')}
                            </Button>
                        </div>
                        <p className="mt-3 h-5 text-caption text-danger">{error}</p>
                        {bsConfig?.waiting_list_url && (
                            <p className="text-caption text-text-2">
                                {localize('com_invite_no_code_tip')}
                                <a className="text-primary" href={bsConfig.waiting_list_url} target="_blank" rel="noreferrer">
                                    {localize('com_invite_apply_access')}
                                </a>
                            </p>
                        )}
                    </form>
                </div>
            </DialogContent>
        </Dialog>
    )
}
