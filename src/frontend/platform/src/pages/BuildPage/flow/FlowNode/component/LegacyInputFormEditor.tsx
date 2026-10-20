import { Button, Input } from '@bisheng/ui';


import { Label } from "@/components/bs-ui/label";
import { AppHint as QuestionTooltip } from "@/pages/BuildPage/components/AppHint";
import { Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { Type } from "lucide-react";
import { useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import DragOptions from "./DragOptions";
import FileTypeSelect from "./FileTypeSelect";
import InputItem from "./InputItem";
import VarInput from "./VarInput";

import type React from "react";
import { FormType,names,type InputFormDraft,type InputFormEditorProps,type InputOption,type SerializedInputField } from "./inputFormTypes";
export function LegacyInputFormEditor({ nodeId, nodeData, initialData, onSubmit, onCancel, existingOptions }: InputFormEditorProps) {
    const { t } = useTranslation('flow');
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"),
        [FormType.Select]: t("categoryExample"),
        [FormType.File]: t("uploadExample"),
    };

    const [formData, setFormData] = useState<InputFormDraft>({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        filecontent: '',
        filepath: '',
        fileType: 'all',
        fileContentSize: 15000,
        imageFile: '',
        isMultiple: true, // default value for multiple file upload
        isRequired: true,
        allowMultiple: false,  // Allow multiple file uploads
        options: [],  // Options for Select input
    });
    const [errors, setErrors] = useState<Record<string, string>>({});
    const editRef = useRef(false);
    const oldFormTypeRef = useRef('')
    const displayNameRef = useRef({
        [FormType.Text]: '',
        [FormType.Select]: '',
        [FormType.File]: '',
    });


    const oldVarNameRef = useRef("");
    const oldcontentNameRef = useRef("");
    const oldPathNameRef = useRef("");
    const oldImageFileRef = useRef("");
    useEffect(() => {
        editRef.current = false
        if (initialData) {
            const {
                type: formType,
                value: displayName,
                key: variableName,
                required: isRequired,
                multiple: allowMultiple,
                file_content: filecontent,
                file_type: fileType,
                file_path: filepath,
                file_content_size: fileContentSize,
                image_file: imageFile,
                options = [] } = initialData;
            setFormData({
                formType,
                displayName,
                variableName,
                isRequired,
                allowMultiple,
                options,
                filecontent,
                fileType,
                filepath,
                fileContentSize,
                imageFile,
                isMultiple: allowMultiple
            });

            editRef.current = true
            oldFormTypeRef.current = formType
            oldVarNameRef.current = variableName;
            oldcontentNameRef.current = filecontent;
            oldPathNameRef.current = filepath;
            oldImageFileRef.current = imageFile;
        }
    }, [initialData]);


    useEffect(() => {
        if (initialData) return

        let initialVarName = names[formData.formType];
        let initialFileContent = 'file_content'
        let initialFilePath = 'file_path'
        let initialFileImage = 'image_file'
        let counter = 1;
        let initialFileContentCounter = 1;
        let initialFilePathCounter = 1;
        let initialFileImageCounter = 1
        while (existingOptions?.some(opt => opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        const fileOtions = existingOptions?.filter(opt => opt.type === FormType.File)
        while (fileOtions?.some(opt => opt.file_content === initialFileContent)) {
            initialFileContentCounter += 1;
            initialFileContent = `file_content${initialFileContentCounter}`;
        }
        while (fileOtions?.some(opt => opt.file_path === initialFilePath)) {
            initialFilePathCounter += 1;
            initialFilePath = `file_path${initialFilePathCounter}`;
        }
        while (fileOtions?.some(opt => opt.image_file === initialFileImage)) {
            initialFileImageCounter += 1;
            initialFileImage = `image_file${initialFileImageCounter}`;
        }

        // existingOptions.
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
            filecontent: initialFileContent,
            filepath: initialFilePath,
            imageFile: initialFileImage
        }));
    }, [initialData, formData.formType, existingOptions])

    const validateForm = () => {
        const newErrors: Record<string, string> = {};

        if (!formData.displayName.trim()) {
            newErrors.displayName = t("displayNameRequired");
        } else if (formData.displayName.length > 50) {
            newErrors.displayName = t("displayNameTooLong");
        }

        if (!formData.variableName.trim()) {
            newErrors.variableName = t("variableNameRequired");
        } else if (formData.variableName.length > 50) {
            newErrors.variableName = t("variableNameTooLong");
        } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.variableName)) {
            newErrors.variableName = t("variableNameInvalid");
        } else if (
            existingOptions?.some(opt => opt.key === formData.variableName) &&
            formData.variableName !== oldVarNameRef.current
        ) {
            newErrors.variableName = t("variableNameExists");
        }

        if (formData.formType === FormType.Select && !formData.options.length) {
            newErrors.options = t("optionsRequired");
        }

        // Validation for file upload variables (if multiple files are allowed)
        if (formData.formType === FormType.File) {
            // Validate file content variable name
            if (!formData.filecontent.trim()) {
                newErrors.filecontent = t("variableNameRequired");
            } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filecontent)) {
                newErrors.filecontent = t("variableNameInvalid");
            } else if (formData.filecontent.length > 50) {
                newErrors.filecontent = t("variableNameTooLong");
            } else if (
                existingOptions?.some(opt => opt.type === 'file'
                    && opt.file_content === formData.filecontent)
                && formData.filecontent !== oldcontentNameRef.current
            ) {
                newErrors.filecontent = t("variableNameExists");
            }

            // Validate file path variable name
            if (!formData.filepath.trim()) {
                newErrors.filepath = t("variableNameRequired");
            } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filepath)) {
                newErrors.filepath = t("variableNameInvalid");
            } else if (formData.filepath.length > 50) {
                newErrors.filepath = t("variableNameTooLong");
            } else if (
                existingOptions?.some(opt => opt.type === 'file'
                    && opt.file_path === formData.filepath)
                && formData.filepath !== oldPathNameRef.current
            ) {
                newErrors.filepath = t("variableNameExists");
            }

            if (formData.fileType !== 'file') {
                const _error = validateImageFileVariableName(formData.imageFile, existingOptions);
                if (_error) {
                    newErrors.imageFile = _error
                }
            }
        }


        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const validateImageFileVariableName = (varName: string, existingOptions: SerializedInputField[] | undefined) => {


        if (!varName || !varName.trim()) {
            return t('variableNameCannotBeEmpty');
        }


        if (/^\d/.test(varName)) {
            return t('variableNameCannotStartWithNumber');
        }


        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(varName)) {
            return t('variableNameContainsInvalidCharacters');
        }


        if (varName.length > 50) {
            return t('variableNameTooLong');
        }


        if (existingOptions?.some(opt => opt.type === 'file'
            && opt.image_file === formData.imageFile)
            && formData.imageFile !== oldImageFileRef.current) {
            return t('variableNameAlreadyExists');
        }

        return '';
    };

    const handleFormSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (validateForm()) {
            onSubmit(formData);
        }
    };

    const updateOptions = (options: InputOption[]) => {
        setFormData((prevData) => ({
            ...prevData,
            options,
        }));
    };

    // if the form type hasn't changed, it keeps the variable name as it was. Otherwise, it generates a new unique variable name.
    const handleChangeFormType = (formType) => {
        displayNameRef.current[formData.formType] = formData.displayName;
        const displayName = displayNameRef.current[formType] || '';
        setFormData({ ...formData, displayName, formType })
        setErrors({});
        if (editRef.current) {
            if (oldFormTypeRef.current === formType) {
                setFormData({ ...formData, formType, variableName: oldVarNameRef.current, displayName })
            } else {
                let counter = 1;
                let initialVarName = names[formType];
                while (existingOptions?.some(opt => opt.key === initialVarName)) {
                    counter += 1;
                    initialVarName = `${names[formType]}${counter}`;
                }
                setFormData({ ...formData, formType, variableName: initialVarName, displayName })
            }
        }
    }

    // var check
    const checkVarFuncRef = useRef<(() => unknown) | null>(null);
    useEffect(() => {
        if (initialData && checkVarFuncRef.current && formData.formType === FormType.Text) {
            checkVarFuncRef.current();
        }
    }, [formData.formType, initialData])

    // text form
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
                value={formData.displayName}
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
        <FileTypeSelect data={{
            label: t('uploadFileTypes'),
            value: formData.fileType,
        }} onChange={(fileType) => setFormData({ ...formData, fileType })} />
        <div>
            <Label className="flex items-center bisheng-label">
                {t('tempKnowledgeBaseName')}
                <QuestionTooltip content={t('tempKnowledgeBaseNameTip')} />
            </Label>
            <Input id="variableName" placeholder={t("enterVariableName")} value={formData.variableName} onChange={(e) => setFormData({ ...formData, variableName: e.target.value })} className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`} />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>

        <div>
            <Label className="flex items-center bisheng-label">
                {t('fileContentVarName')}
                <QuestionTooltip content={t('fileContentVarTip')} />
            </Label>
            <Input id="filecontent" placeholder={t("enterVariableName")} value={formData.filecontent} onChange={(e) => setFormData({ ...formData, filecontent: e.target.value })} className={`mt-2 ${errors.filecontent ? "border-red-500" : ""}`} />
            {errors.filecontent && <p className="text-red-500 text-sm">{errors.filecontent}</p>}
        </div>
        <InputItem
            type='number'
            char
            linefeed
            label={t('fileContentMaxLength')}
            data={
                {
                    min: 0,
                    value: formData.fileContentSize,
                }
            }
            onChange={(fileContentSize: number) => setFormData({ ...formData, fileContentSize })}
        />
        <div>
            <Label className="flex items-center bisheng-label">
                {t('filePathVarName')}
                <QuestionTooltip content={t('filePathVarTip')} />
            </Label>
            <Input id="filepath" placeholder={t("enterVariableName")} value={formData.filepath} onChange={(e) => setFormData({ ...formData, filepath: e.target.value })} className={`mt-2 ${errors.filepath ? "border-red-500" : ""}`} />
            {errors.filepath && <p className="text-red-500 text-sm">{errors.filepath}</p>}
        </div>
        {formData.fileType !== 'file' && <div>
            <Label className="flex items-center bisheng-label">
                {t('uploadImageFile')}
                <QuestionTooltip content={t('uploadImageFileTip')} />
            </Label>
            <Input id="imageFile" placeholder={t("enterVariableName")} value={formData.imageFile} onChange={(e) => setFormData({ ...formData, imageFile: e.target.value })} className={`mt-2 ${errors.imageFile ? "border-red-500" : ""}`} />
            {errors.imageFile && <p className="text-red-500 text-sm">{errors.imageFile}</p>}
        </div>}
    </div>;

    return (
        <form onSubmit={handleFormSubmit} className="space-y-4">
            <div>
                <Label className="bisheng-label">{t("formType")}</Label>
                <div className="grid grid-cols-3 gap-4 mt-2">
                    <Button className={`flex flex-col h-auto w-full min-w-0 gap-1 py-2 ${formData.formType === FormType.Text ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`} type="button" variant="outlined" onClick={() => handleChangeFormType(FormType.Text)} color="default">
                        <Type size={18} />
                        {t("textInput")}
                    </Button>
                    <Button className={`flex flex-col h-auto w-full min-w-0 gap-1 py-2 ${formData.formType === FormType.Select ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`} type="button" variant="outlined" onClick={() => handleChangeFormType(FormType.Select)} color="default">
                        <Outlined.DoubleDown size={18} />
                        {t("dropdown")}
                    </Button>
                    <Button className={`flex flex-col h-auto w-full min-w-0 gap-1 py-2 ${formData.formType === FormType.File ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`} type="button" variant="outlined" onClick={() => handleChangeFormType(FormType.File)} color="default">
                        <Outlined.Upload size={18} />
                        {t("file")}
                    </Button>
                </div>
            </div>

            {formData.formType === FormType.Text && (InputForm)}
            {formData.formType === FormType.Select && (SelectForm)}
            {formData.formType === FormType.File && (FileForm)}

            <div className="flex space-x-4 justify-end">
                <Button className="px-8" type="button" variant="outlined" onClick={onCancel} color="default">
                    {t("cancel")}
                </Button>
                <Button className="px-8" type="submit">
                    {t("confirm")}
                </Button>
            </div>
        </form>
    );
}

// node input form item
