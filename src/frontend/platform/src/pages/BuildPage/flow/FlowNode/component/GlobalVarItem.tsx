"use client"

import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { QuestionTooltip, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { generateUUID } from "@/components/bs-ui/utils"
import { MinusCircle, PencilLine, Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface Variable {
    key: string // UUID generated
    label: string // User input variable name
    value: string // Variable value
}

interface ValidationError {
    label?: string
    value?: string
}

export default function GlobalVarItem({ data, onChange, i18nPrefix }) {
    const [variables, setVariables] = useState<Variable[]>(data.value)
    const [isDialogOpen, setIsDialogOpen] = useState(false)
    const [editingVariable, setEditingVariable] = useState<Variable | null>(null)
    const [hoveredRow, setHoveredRow] = useState<string | null>(null)
    const [formData, setFormData] = useState({ label: "", value: "" })
    const [errors, setErrors] = useState<ValidationError>({})
    const { t } = useTranslation('flow')

    const validateVariableLabel = (label: string, currentKey?: string): string | null => {
        if (!label) {
            return t('variableNameEmpty')
        }
        if (label.length > 50) {
            return t('variableNameTooLong')
        }
        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(label)) {
            if (/^[0-9]/.test(label)) {
                return t('variableNameStartsWithNumber')
            }
            return t('variableNameInvalidChars')
        }
        if (variables.some((v) => v.label === label && v.key !== currentKey)) {
            return t('variableNameDuplicate')
        }
        return null
    }

    const validateVariableValue = (value: string): string | null => {
        if (!value) {
            return t('variableValueEmpty')
        }
        if (value.length > 1000) {
            return t('variableValueTooLong')
        }
        return null
    }

    const handleOpenDialog = (variable?: Variable) => {
        if (variable) {
            setEditingVariable(variable)
            setFormData({ label: variable.label, value: variable.value })
        } else {
            setEditingVariable(null)
            setFormData({ label: "", value: "" })
        }
        setErrors({})
        setIsDialogOpen(true)
    }

    const handleCloseDialog = () => {
        setIsDialogOpen(false)
        setEditingVariable(null)
        setFormData({ label: "", value: "" })
        setErrors({})
    }

    const handleSave = () => {
        const labelError = validateVariableLabel(formData.label, editingVariable?.key)
        const valueError = validateVariableValue(formData.value)

        if (labelError || valueError) {
            setErrors({
                label: labelError || undefined,
                value: valueError || undefined,
            })
            return
        }

        if (editingVariable) {
            setVariables((prev) =>
                prev.map((v) => (v.key === editingVariable.key ? { ...v, label: formData.label, value: formData.value } : v)),
            )
        } else {
            setVariables((prev) => [
                ...prev,
                {
                    key: generateUUID(6),
                    label: formData.label,
                    value: formData.value,
                },
            ])
        }

        handleCloseDialog()
    }

    const handleDelete = (key: string) => {
        setVariables((prev) => prev.filter((v) => v.key !== key))
    }

    useEffect(() => {
        onChange(variables)
    }, [variables])

    return (
        <div className="w-full max-w-3xl">
            <div className="space-y-4">
                {/* Header */}
                <Label className="flex items-center bisheng-label">
                    {t(`${i18nPrefix}label`)}
                    {data.help && <QuestionTooltip content={t(`${i18nPrefix}help`)} />}
                </Label>
                {/* Add Variable Button */}
                <Button onClick={() => handleOpenDialog()} variant='outline' className="border-primary text-primary mt-2">
                    <Plus className="size-4 mr-1" />
                    {t('addVariable')}
                </Button>

                {/* Variables List */}
                {variables.length > 0 && (
                    <div className="space-y-2">
                        {/* Table Header */}
                        <div className="grid grid-cols-6 gap-4 text-xs text-muted-foreground">
                            <div className="col-span-2">{t('variableName')}</div>
                            <div className="col-span-3">{t('variableValue')}</div>
                        </div>

                        {/* Variable Rows */}
                        {variables.map((variable) => (
                            <div
                                key={variable.key}
                                className="grid grid-cols-6 gap-4 pb-1 rounded hover:bg-muted/50 transition-colors group relative"
                                onMouseEnter={() => setHoveredRow(variable.key)}
                                onMouseLeave={() => setHoveredRow(null)}
                            >
                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <div className="col-span-2">
                                                <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0] truncate max-w-full block">{variable.label}</Badge>
                                            </div>
                                        </TooltipTrigger>
                                        <TooltipContent align="start" className="max-w-xs">
                                            <p className="break-all">{variable.label}</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>

                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <div className="text-sm text-foreground cursor-default truncate col-span-3 overflow-hidden">
                                                {variable.value}
                                            </div>
                                        </TooltipTrigger>
                                        <TooltipContent align="start" className="max-w-xs">
                                            <p className="break-all whitespace-pre-wrap">{variable.value}</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>

                                {/* Action Buttons */}
                                {hoveredRow === variable.key && (
                                    <div className="absolute -right-1 -top-1 flex">
                                        <Button variant="ghost" size="icon" className="size-7" onClick={() => handleOpenDialog(variable)}>
                                            <PencilLine className="size-3.5" />
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="size-7 hover:text-destructive"
                                            onClick={() => handleDelete(variable.key)}
                                        >
                                            <MinusCircle className="size-3.5" />
                                        </Button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Add/Edit Dialog */}
            <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>{editingVariable ? t('editGlobalVariable') : t('addGlobalVariable')}</DialogTitle>
                    </DialogHeader>

                    <div className="space-y-4 py-2">
                        {/* Variable Name */}
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <Label className="flex items-center bisheng-label">
                                    {t('variableName')}
                                    <QuestionTooltip content={t('variableNameRuleTip')} />
                                </Label>
                            </div>
                            <Input
                                id="variable-label"
                                placeholder={t('enterVariableName')}
                                value={formData.label}
                                onChange={(e) => {
                                    setFormData({ ...formData, label: e.target.value })
                                    if (errors.label) {
                                        setErrors({ ...errors, label: undefined })
                                    }
                                }}
                                className={errors.label ? "border-destructive" : ""}
                            />
                            {errors.label && <p className="text-xs text-destructive">{errors.label}</p>}
                        </div>

                        {/* Variable Value */}
                        <div className="space-y-2">
                            <div className="flex items-center gap-2">
                                <Label className="flex items-center bisheng-label">
                                    {t('variableValue')}
                                    <QuestionTooltip content={t('variableValueRuleTip')} />
                                </Label>
                            </div>
                            <Textarea
                                id="variable-value"
                                placeholder={t('enterVariableValue')}
                                value={formData.value}
                                onChange={(e) => {
                                    setFormData({ ...formData, value: e.target.value })
                                    if (errors.value) {
                                        setErrors({ ...errors, value: undefined })
                                    }
                                }}
                                className={`min-h-20 max-h-40 resize-none ${errors.value ? "border-destructive" : ""}`}
                            />
                            {errors.value && <p className="text-xs text-destructive">{errors.value}</p>}
                        </div>
                    </div>

                    <DialogFooter className="gap-2 sm:gap-0">
                        <Button variant="outline" onClick={handleCloseDialog}>
                            {t('cancel')}
                        </Button>
                        <Button onClick={handleSave}>{t('confirm')}</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
