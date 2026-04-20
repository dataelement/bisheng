import { Button, LoadButton } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useOrgSyncStore } from "@/store/orgSyncStore"
import {
  OrgSyncConfig,
  OrgSyncProvider,
} from "@/types/api/orgSync"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  FeishuFieldSet,
  FEISHU_INITIAL,
  FeishuFormValues,
  makeFeishuSubmitPayload,
  validateFeishuForm,
} from "./fieldsets/FeishuFieldSet"
import {
  GENERIC_API_INITIAL,
  GenericApiFieldSet,
  GenericApiFormValues,
  makeGenericApiSubmitPayload,
  validateGenericApiForm,
} from "./fieldsets/GenericApiFieldSet"
import {
  makeWeComSubmitPayload,
  validateWeComForm,
  WECOM_INITIAL,
  WeComFieldSet,
  WeComFormValues,
} from "./fieldsets/WeComFieldSet"

interface ProviderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  editingConfig: OrgSyncConfig | null
}

const SUPPORTED_PROVIDERS: OrgSyncProvider[] = [
  "wecom",
  "feishu",
  "generic_api",
]

type FieldErrors = Record<string, string>

export function ProviderDialog({
  open,
  onOpenChange,
  editingConfig,
}: ProviderDialogProps) {
  const { t } = useTranslation("orgSync")
  const { message } = useToast()
  const createConfig = useOrgSyncStore((s) => s.createConfig)
  const updateConfig = useOrgSyncStore((s) => s.updateConfig)
  const editLoading = useOrgSyncStore((s) => s.editLoading)

  const isEdit = !!editingConfig

  const [configName, setConfigName] = useState("")
  const [provider, setProvider] = useState<OrgSyncProvider>("wecom")
  const [wecomValues, setWecomValues] = useState<WeComFormValues>(WECOM_INITIAL)
  const [feishuValues, setFeishuValues] = useState<FeishuFormValues>(FEISHU_INITIAL)
  const [genericValues, setGenericValues] = useState<GenericApiFormValues>(
    GENERIC_API_INITIAL
  )
  const [nameError, setNameError] = useState("")
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})

  // Reset / populate whenever dialog opens
  useEffect(() => {
    if (!open) return

    setNameError("")
    setFieldErrors({})

    if (editingConfig) {
      setConfigName(editingConfig.config_name)
      setProvider(editingConfig.provider)
      const auth = (editingConfig.auth_config || {}) as Record<string, unknown>

      if (editingConfig.provider === "wecom") {
        setWecomValues({
          corpid: String(auth.corpid ?? ""),
          corpsecret: String(auth.corpsecret ?? "****"),
          agent_id: String(auth.agent_id ?? ""),
          allow_dept_ids: Array.isArray(auth.allow_dept_ids)
            ? (auth.allow_dept_ids as unknown[]).filter(
                (x): x is number => Number.isInteger(x)
              )
            : [],
        })
      } else if (editingConfig.provider === "feishu") {
        setFeishuValues({
          app_id: String(auth.app_id ?? ""),
          app_secret: String(auth.app_secret ?? "****"),
        })
      } else if (editingConfig.provider === "generic_api") {
        setGenericValues({
          endpoint_url: String(auth.endpoint_url ?? ""),
          api_key: String(auth.api_key ?? "****"),
        })
      }
    } else {
      setConfigName("")
      setProvider("wecom")
      setWecomValues(WECOM_INITIAL)
      setFeishuValues(FEISHU_INITIAL)
      setGenericValues(GENERIC_API_INITIAL)
    }
  }, [open, editingConfig])

  const handleProviderChange = (next: OrgSyncProvider) => {
    setProvider(next)
    setFieldErrors({})
  }

  const buildPayload = (): {
    payload: {
      provider: OrgSyncProvider
      config_name: string
      auth_type: string
      auth_config: Record<string, unknown>
    } | null
    errors: FieldErrors
    nameErr: string
  } => {
    const nameErr = configName.trim() ? "" : t("validation.nameRequired")

    let errors: FieldErrors = {}
    let authConfig: Record<string, unknown> = {}

    if (provider === "wecom") {
      errors = validateWeComForm(wecomValues, isEdit, t) as FieldErrors
      authConfig = makeWeComSubmitPayload(wecomValues, isEdit)
    } else if (provider === "feishu") {
      errors = validateFeishuForm(feishuValues, isEdit, t) as FieldErrors
      authConfig = makeFeishuSubmitPayload(feishuValues, isEdit)
    } else if (provider === "generic_api") {
      errors = validateGenericApiForm(genericValues, isEdit, t) as FieldErrors
      authConfig = makeGenericApiSubmitPayload(genericValues, isEdit)
    }

    if (nameErr || Object.keys(errors).length > 0) {
      return { payload: null, errors, nameErr }
    }

    return {
      payload: {
        provider,
        config_name: configName.trim(),
        auth_type: "api_key",
        auth_config: authConfig,
      },
      errors,
      nameErr,
    }
  }

  const handleSubmit = () => {
    const { payload, errors, nameErr } = buildPayload()
    setNameError(nameErr)
    setFieldErrors(errors)
    if (!payload) return

    const task = isEdit
      ? updateConfig(editingConfig!.id, {
          config_name: payload.config_name,
          auth_config: payload.auth_config,
        })
      : createConfig(payload)

    captureAndAlertRequestErrorHoc(task).then((ok) => {
      if (ok !== false) {
        message({
          title: isEdit ? t("updateSuccess") : t("createSuccess"),
          description: payload!.config_name,
          variant: "success",
        })
        onOpenChange(false)
      }
    })
  }

  const renderFieldSet = useMemo(() => {
    if (provider === "wecom") {
      return (
        <WeComFieldSet
          value={wecomValues}
          onChange={setWecomValues}
          isEdit={isEdit}
          errors={fieldErrors as Partial<Record<keyof WeComFormValues, string>>}
        />
      )
    }
    if (provider === "feishu") {
      return (
        <FeishuFieldSet
          value={feishuValues}
          onChange={setFeishuValues}
          isEdit={isEdit}
          errors={fieldErrors as Partial<Record<keyof FeishuFormValues, string>>}
        />
      )
    }
    return (
      <GenericApiFieldSet
        value={genericValues}
        onChange={setGenericValues}
        isEdit={isEdit}
        errors={
          fieldErrors as Partial<Record<keyof GenericApiFormValues, string>>
        }
      />
    )
  }, [provider, wecomValues, feishuValues, genericValues, fieldErrors, isEdit])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t("dialog.editTitle") : t("dialog.createTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="org-sync-name">
              {t("form.configName")}{" "}
              <span className="text-destructive">*</span>
            </Label>
            <Input
              id="org-sync-name"
              value={configName}
              onChange={(e) => setConfigName(e.target.value)}
              placeholder={t("form.configNamePlaceholder")}
              disabled={false}
            />
            {nameError && (
              <span className="text-xs text-destructive">{nameError}</span>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <Label>{t("form.provider")}</Label>
            <Select
              value={provider}
              onValueChange={(v) => handleProviderChange(v as OrgSyncProvider)}
              disabled={isEdit}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUPPORTED_PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {t(`providers.${p}`, p)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {isEdit && (
              <span className="text-xs text-muted-foreground">
                {t("form.providerImmutable")}
              </span>
            )}
          </div>

          {renderFieldSet}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("actions.cancel")}
          </Button>
          <LoadButton loading={editLoading} onClick={handleSubmit}>
            {t("actions.save")}
          </LoadButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
