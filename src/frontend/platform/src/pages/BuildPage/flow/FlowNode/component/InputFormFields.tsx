import { Input, Select } from '@bisheng/ui';
import type { UploadFileKind } from "@/util/fileAcceptUtils";

import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { Switch } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import DragOptions from "./DragOptions";
import FileTypeSelect from "./FileTypeSelect";
import InputItem from "./InputItem";
import VarInput from "./VarInput";

import type { WorkflowNodeParam } from "@/types/flow";
import type React from "react";
import { FormOption,FormType,type InputFormDraft,type InputOption } from "./inputFormTypes";
interface InputFormFieldsProps {
    formData: InputFormDraft;
    setFormData: React.Dispatch<React.SetStateAction<InputFormDraft>>;
    errors: Record<string, string>;
    nodeId: string;
    nodeData: WorkflowNodeParam;
    defaultValue: string;
    namePlaceholders: Record<FormType, string>;
    checkVarFuncRef: React.MutableRefObject<(() => unknown) | null>;
    updateOptions: (options: InputOption[]) => void;
    handleFileTypeChange: (value: UploadFileKind[]) => void;
    handleProcessingStrategyChange: (value: FormOption) => void;
    getAvailableProcessingStrategies: () => { value: FormOption; label: string }[];
    shouldShowField: (field: string) => boolean;
}
export function InputFormFields({ formData, setFormData, errors, nodeId, nodeData, defaultValue, namePlaceholders, checkVarFuncRef, updateOptions, handleFileTypeChange, handleProcessingStrategyChange, getAvailableProcessingStrategies, shouldShowField }: InputFormFieldsProps) {
    const { t } = useTranslation('flow');
    const selectLabels = useSelectLabels();
    const InputForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            {/* <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            /> */}
            <VarInput
                mini
                key={formData.variableName}
                label={''}
                itemKey={''}
                nodeId={nodeId}
                paramItem={nodeData}
                value={defaultValue}
                placeholder={namePlaceholders[formData.formType]}
                onChange={(val: string) => setFormData({ ...formData, displayName: val })}
                onVarEvent={(func: () => unknown) => checkVarFuncRef.current = func}
            >
            </VarInput>
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input id="variableName" placeholder={t("enterVariableName")} value={formData.variableName} onChange={(e) => setFormData({ ...formData, variableName: e.target.value })} className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`} />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>
    </div>
    // select from
    const SelectForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            <Input id="displayName" placeholder={namePlaceholders[formData.formType]} value={formData.displayName} onChange={(e) => setFormData({ ...formData, displayName: e.target.value })} className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`} />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input id="variableName" placeholder={t("enterVariableName")} value={formData.variableName} onChange={(e) => setFormData({ ...formData, variableName: e.target.value })} className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`} />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        <div>
            <Label className="bisheng-label">{t("options")}</Label>
            <DragOptions edit scroll options={formData.options} onChange={updateOptions} />
            {errors.options && <p className="text-red-500 text-sm">{errors.options}</p>}
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('allowMultipleSelect')}</Label>
            <Switch
                checked={formData.allowMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, allowMultiple: checked })}
            />
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>
    </div>
    // file form
    const FileForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            <Input id="displayName" placeholder={namePlaceholders[formData.formType]} value={formData.displayName} onChange={(e) => setFormData({ ...formData, displayName: e.target.value })} className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`} />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>

        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('isRequired')}</Label>
            <Switch
                checked={formData.isRequired}
                onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
            />
        </div>

        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">{t('allowUploadMultipleFiles')}</Label>
            <Switch
                checked={formData.isMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, isMultiple: checked })}
            />
        </div>

        <FileTypeSelect
            data={{
                label: t('uploadFileTypes'),
                value: formData.fileType,
            }}
            onChange={handleFileTypeChange}
        />

        {}
        <div>
            <Label className="flex items-center bisheng-label">
                {t("fileProcessingStrategy")}
                <QuestionTooltip
                    content={
                        <div className="whitespace-pre-line">
                            {t("dialogProcessingStrategyTip")}
                        </div>
                    }
                />
            </Label>
            <Select
                {...selectLabels}
                options={getAvailableProcessingStrategies().filter((option) => option.value)}
                value={formData.processingOption || null}
                onChange={(v) => {
                    // Re-picking the current strategy is a no-op (Radix never fired for it).
                    if (v != null && v !== formData.processingOption) handleProcessingStrategyChange(v as FormOption);
                }}
                placeholder={t("selectFile")}
                aria-label={t("fileProcessingStrategy")}
                className="mt-2 w-full"
            />
        </div>

        {}
        {shouldShowField('tempKnowledge') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t('tempKnowledgeBaseName')}

                    <QuestionTooltip content={t('tempKnowledgeBaseNameTip')} />
                </Label>
                <Input id="variableName" placeholder={t("enterVariableName")} value={formData.variableName} onChange={(e) => setFormData({ ...formData, variableName: e.target.value })} className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`} />
                {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
            </div>
        )}

        {}
        {shouldShowField('parseContent') && (
            <>
                <InputItem
                    type='number'
                    char
                    linefeed
                    label={t('parseLengthLimit')}
                    data={{
                        min: 0,
                        value: formData.fileContentSize,
                    }}
                    onChange={(fileContentSize: number) => setFormData({ ...formData, fileContentSize })}
                />
                <div>
                    <Label className="flex items-center bisheng-label">
                        {t("parseResultName")}
                        <QuestionTooltip content={t("storeVariableName")} />
                    </Label>
                    <Input id="filecontent" placeholder={t("enterVariableName")} value={formData.filecontent} onChange={(e) => setFormData({ ...formData, filecontent: e.target.value })} className={`mt-2 ${errors.filecontent ? "border-red-500" : ""}`} />
                    {errors.filecontent && <p className="text-red-500 text-sm">{errors.filecontent}</p>}
                </div>
                {errors.fileContentSize && <p className="text-red-500 text-sm">{errors.fileContentSize}</p>}
            </>
        )}

        {}
        {shouldShowField('imageFile') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t("imageVariableName")}
                    <QuestionTooltip content={t('extractImages')} />
                </Label>
                <Input id="imageFile" placeholder={t("enterVariableName")} value={formData.imageFile} onChange={(e) => setFormData({ ...formData, imageFile: e.target.value })} className={`mt-2 ${errors.imageFile ? "border-red-500" : ""}`} />
                {errors.imageFile && <p className="text-red-500 text-sm">{errors.imageFile}</p>}
            </div>
        )}

        {}
        {shouldShowField('filePath') && (
            <div>
                <Label className="flex items-center bisheng-label">
                    {t("filePathName")}
                    <QuestionTooltip content={t('storeUploadFiles')} />
                </Label>
                <Input id="filepath" placeholder={t("enterVariableName")} value={formData.filepath} onChange={(e) => setFormData({ ...formData, filepath: e.target.value })} className={`mt-2 ${errors.filepath ? "border-red-500" : ""}`} />
                {errors.filepath && <p className="text-red-500 text-sm">{errors.filepath}</p>}
            </div>
        )}
    </div>;

    return <>
        {formData.formType === FormType.Text && InputForm}
        {formData.formType === FormType.Select && SelectForm}
        {formData.formType === FormType.File && FileForm}
    </>;
}
