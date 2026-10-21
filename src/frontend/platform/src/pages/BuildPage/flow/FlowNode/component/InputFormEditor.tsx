import { Button } from '@bisheng/ui';
import type { UploadFileKind } from "@/util/fileAcceptUtils";

import { Label } from "@/components/bs-ui/label";
import { acceptsImages } from "@/util/fileAcceptUtils";
import { generateUUID } from "@/utils";
import { Outlined } from "bisheng-icons";
import { Type } from "lucide-react";
import { useEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";

import type React from "react";
import { InputFormFields } from "./InputFormFields";
import { FormOption,FormType,modesToOption,names,optIngests,type InputFormDraft,type InputFormEditorProps,type InputOption,type SerializedInputField } from "./inputFormTypes";
export function InputFormEditor({ nodeId, nodeData, initialData, onSubmit, onCancel, existingOptions }: InputFormEditorProps) {
    const { t } = useTranslation('flow');
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"),
        [FormType.Select]: t("categoryExample"),
        [FormType.File]: t("uploadExample"),
    };
    const processingOptions = useMemo(() => [
        { value: FormOption.ParseOnly, label: t("parseNoIngest") },
        { value: FormOption.ParseIngest, label: t("parseWithIngest") },
        { value: FormOption.NoParse, label: t("notParse") },
    ], [t]);
    const [defaultValue] = useState(initialData?.value || "");
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
        processingOption: FormOption.ParseOnly as FormOption,
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
    const oldStrategyRef = useRef<unknown>("");

    useEffect(() => {

        editRef.current = false;
        oldFormTypeRef.current = '';
        oldVarNameRef.current = '';
        oldcontentNameRef.current = '';
        oldPathNameRef.current = '';
        oldImageFileRef.current = '';
        oldStrategyRef.current = '';

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
                file_content_size: fileContentSize = 15000,
                image_file: imageFile,
                file_parse_mode: processingStrategy,
                options = [],
            } = initialData;

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
                fileContentSize: fileContentSize || 15000,
                imageFile,
                isMultiple: allowMultiple,
                processingOption: modesToOption(processingStrategy),
            });

            editRef.current = true;
            oldFormTypeRef.current = formType;
            oldVarNameRef.current = variableName;
            oldcontentNameRef.current = filecontent;
            oldPathNameRef.current = filepath;
            oldImageFileRef.current = imageFile;
            oldStrategyRef.current = processingStrategy;
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
        let initialFileImageCounter = 1;
        while (existingOptions?.some(opt => optIngests(opt) && opt.type === "file" && opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        while (existingOptions?.some(opt => !optIngests(opt) && opt.file_parse_mode && opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        const fileOtions = existingOptions?.filter(opt => opt.type === FormType.File);
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


        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
            filecontent: initialFileContent,
            filepath: initialFilePath,
            imageFile: initialFileImage
        }));
    }, [initialData, existingOptions, formData.formType])

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
            // newErrors.variableName = t("variableNameExists");
        }

        if (formData.formType === FormType.Select && !formData.options.length) {
            newErrors.options = t("optionsRequired");
        }

        // Validation for file upload variables — validate every visible field by the
        // unified rule (mirrors shouldShowField): path always, image by upload type,
        // content when parsing, temp-KB name (=variableName) when ingesting.
        if (formData.formType === FormType.File) {
            const isParse = formData.processingOption === FormOption.ParseOnly
                || formData.processingOption === FormOption.ParseIngest;
            const isImageCapable = acceptsImages(formData.fileType);


            if (isParse) {
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
            }


            if (isImageCapable) {
                const _error = validateImageFileVariableName(formData.imageFile, existingOptions);
                if (_error) {
                    newErrors.imageFile = _error
                }
            }


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
            && opt.image_file === varName)
            && varName !== oldImageFileRef.current) {
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
    const handleChangeFormType = (formType: FormType) => {
        displayNameRef.current[formData.formType] = formData.displayName;
        const displayName = displayNameRef.current[formType] || '';

        setFormData(prev => {

            let variableName = prev.variableName;

            if (editRef.current) {
                if (oldFormTypeRef.current === formType) {
                    variableName = oldVarNameRef.current;
                } else {

                    let counter = 1;
                    const baseName = names[formType];
                    let name = baseName;
                    while (existingOptions?.some(opt => opt.key === name)) {
                        counter += 1;
                        name = `${baseName}${counter}`;
                    }
                    variableName = name;
                }
            } else {

                let counter = 1;
                const baseName = names[formType];
                let name = baseName;
                while (existingOptions?.some(opt => opt.key === name)) {
                    counter += 1;
                    name = `${baseName}${counter}`;
                }
                variableName = name;
            }

            return { ...prev, formType, displayName, variableName };
        });

        setErrors({});
    };



    const handleFileTypeChange = (fileType: UploadFileKind[]) => {

        setErrors({});

        setFormData(prev => {
            const updates: Partial<InputFormDraft> = { fileType };
            const fileOptions = existingOptions?.filter(opt => opt.type === FormType.File) || [];
            const isImageCapable = acceptsImages(fileType);

            // Image variable only exists for image-capable types. Backfill a unique name
            // when switching into such a type with no value yet — e.g. editing an item
            // that was saved as document-only, where image_file was cleared on submit and
            // the new-item auto-fill effect is skipped in edit mode (initialData present).
            if (isImageCapable && (!prev.imageFile || prev.imageFile.trim() === '')) {
                let name = 'image_file';
                let counter = 1;
                while (fileOptions.some(opt => opt.image_file === name)) {
                    counter += 1;
                    name = `image_file${counter}`;
                }
                updates.imageFile = name;
            }

            // File path is always exposed now; backfill if somehow empty (legacy items).
            if (!prev.filepath || prev.filepath.trim() === '') {
                let name = 'file_path';
                let counter = 1;
                while (fileOptions.some(opt => opt.file_path === name)) {
                    counter += 1;
                    name = `file_path${counter}`;
                }
                updates.filepath = name;
            }

            return { ...prev, ...updates };
        });
    }


    const handleProcessingStrategyChange = (option: FormOption) => {
        setErrors({});

        setFormData(prev => {
            const updates: Partial<InputFormDraft> = { processingOption: option };
            const fileOptions = existingOptions?.filter(opt => opt.type === FormType.File) || [];
            const willIngest = option === FormOption.ParseIngest;
            const wasIngest = prev.processingOption === FormOption.ParseIngest;
            const isParse = willIngest || option === FormOption.ParseOnly;


            if (willIngest && !wasIngest) {
                let name = 'file';
                let counter = 1;
                while (fileOptions.some(opt => opt.key === name)) {
                    counter += 1;
                    name = `file${counter}`;
                }
                updates.variableName = name;
            } else if (editRef.current && wasIngest && !willIngest) {
                updates.variableName = `file_${generateUUID(6)}`;
            }


            if (isParse && (!prev.filecontent || prev.filecontent.trim() === '')) {
                let name = 'file_content';
                let counter = 1;
                while (fileOptions.some(opt => opt.file_content === name)) {
                    counter += 1;
                    name = `file_content${counter}`;
                }
                updates.filecontent = name;
            }

            return { ...prev, ...updates };
        });
    };

    const getAvailableProcessingStrategies = () => {
        return processingOptions;
    };


    const shouldShowField = (fieldType: string) => {
        if (formData.formType !== FormType.File) return false;

        const option = formData.processingOption;
        const isParse = option === FormOption.ParseOnly || option === FormOption.ParseIngest;
        const isImageCapable = acceptsImages(formData.fileType);

        switch (fieldType) {
            case 'tempKnowledge':
                return option === FormOption.ParseIngest;
            case 'parseContent':
                return isParse;
            case 'imageFile':
                return isImageCapable;
            case 'filePath':
                return true;
            default:
                return false;
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

    return (
        // Only the field area scrolls; the action row stays put. The file form
        // alone has eight fields, which does not fit a 570px-tall screen, and
        // without this the submit button was pushed off the bottom.
        <form onSubmit={handleFormSubmit} className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-0.5">
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

            <InputFormFields {...{ formData, setFormData, errors, nodeId, nodeData, defaultValue, namePlaceholders, checkVarFuncRef, updateOptions, handleFileTypeChange, handleProcessingStrategyChange, getAvailableProcessingStrategies, shouldShowField }} />
            </div>

            <div className="flex shrink-0 space-x-4 justify-end pt-4">
                <Button type="button" variant="outlined" onClick={onCancel} color="default">
                    {t("cancel")}
                </Button>
                <Button type="submit">
                    {t("confirm")}
                </Button>
            </div>
        </form>
    );
}
