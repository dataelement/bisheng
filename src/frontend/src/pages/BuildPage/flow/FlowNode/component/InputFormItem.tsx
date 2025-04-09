import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ChevronsDown, CloudUpload, Type } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化
import DragOptions from "./DragOptions";

const enum FormType {
    Text = "text",
    Select = "select",
    File = "file",
}

const names = {
    [FormType.Text]: "text_input",
    [FormType.Select]: "category",
    [FormType.File]: "file",
}

function Form({ initialData, onSubmit, onCancel, existingOptions }) {
    const { t } = useTranslation('flow');
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"), // 例如“姓名”
        [FormType.Select]: t("categoryExample"), // 例如“保险类别”
        [FormType.File]: t("uploadExample"), // 例如“请上传去年财报”
    };

    const [formData, setFormData] = useState({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        filecontent: '',
        filepath: '',
        isMultiple: true, // default value for multiple file upload
        isRequired: true,
        allowMultiple: false,  // Allow multiple file uploads
        options: [],  // Options for Select input
    });
    const [errors, setErrors] = useState<any>({});
    const editRef = useRef(false); // 编辑状态
    const oldFormTypeRef = useRef('')

    const oldVarNameRef = useRef("");
    const oldcontentNameRef = useRef("");
    const oldPathNameRef = useRef("");
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
                file_path: filepath,
                options = [] } = initialData;
            setFormData({
                formType,
                displayName,
                variableName,
                isRequired,
                allowMultiple,
                options,
                filecontent,
                filepath,
                isMultiple: allowMultiple
            });

            editRef.current = true
            oldFormTypeRef.current = formType
            oldVarNameRef.current = variableName;
            oldcontentNameRef.current = filecontent;
            oldPathNameRef.current = filepath;
        }
    }, [initialData]);

    // 变量重命名
    useEffect(() => {
        if (initialData) return
        // 初始化变量名
        let initialVarName = names[formData.formType];
        let initialFileContent = 'file_content'
        let initialFilePath = 'file_path'
        let counter = 1;
        let initialFileContentCounter = 1;
        let initialFilePathCounter = 1;
        while (existingOptions?.some(opt => opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        const fileOtions = existingOptions?.filter(opt => opt.type === FormType.File && !opt.multiple)
        while (fileOtions?.some(opt => opt.file_content === initialFileContent)) {
            initialFileContentCounter += 1;
            initialFileContent = `file_content${initialFileContentCounter}`;
        }
        while (fileOtions?.some(opt => opt.file_path === initialFilePath)) {
            initialFilePathCounter += 1;
            initialFilePath = `file_path${initialFilePathCounter}`;
        }
        // 变量重命名
        // existingOptions.
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
            filecontent: initialFileContent,
            filepath: initialFilePath
        }));
    }, [initialData, formData.formType])

    const validateForm = () => {
        const newErrors: any = {};

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
        if (formData.formType === FormType.File && !formData.isMultiple) {
            // Validate file content variable name
            if (!formData.filecontent.trim()) {
                newErrors.filecontent = t("variableNameRequired");
            } else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(formData.filecontent)) {
                newErrors.filecontent = t("variableNameInvalid");
            } else if (formData.filecontent.length > 50) {
                newErrors.filecontent = t("variableNameTooLong");
            } else if (
                existingOptions?.some(opt => !opt.multiple && opt.file_content === formData.filecontent) &&
                formData.filecontent !== oldcontentNameRef.current
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
                existingOptions?.some(opt => !opt.multiple && opt.file_path === formData.filepath) &&
                formData.filepath !== oldPathNameRef.current
            ) {
                newErrors.filepath = t("variableNameExists");
            }
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleFormSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            onSubmit(formData);
        }
    };

    const updateOptions = (options) => {
        setFormData((prevData) => ({
            ...prevData,
            options,
        }));
    };

    // if the form type hasn't changed, it keeps the variable name as it was. Otherwise, it generates a new unique variable name.
    const handleChangeFormType = (formType) => {
        setFormData({ ...formData, formType })
        if (editRef.current) {
            if (oldFormTypeRef.current === formType) {
                setFormData({ ...formData, formType, variableName: oldVarNameRef.current })
            } else {
                let counter = 1;
                let initialVarName = names[formType];
                while (existingOptions?.some(opt => opt.key === initialVarName)) {
                    counter += 1;
                    initialVarName = `${names[formType]}${counter}`;
                }
                setFormData({ ...formData, formType, variableName: initialVarName })
            }
        }
    }
    // text form
    const InputForm = <div className="space-y-4">
        <div>
            <Label className="flex items-center bisheng-label">
                {t("displayName")}
                <QuestionTooltip content={t("displayNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
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
            <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            />
            {errors.displayName && <p className="text-red-500 text-sm">{errors.displayName}</p>}
        </div>
        <div>
            <Label className="flex items-center bisheng-label">
                {t("variableName")}
                <QuestionTooltip content={t("variableNameTooltip")} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        <div>
            <Label className="bisheng-label">{t("options")}</Label>
            <DragOptions edit scroll options={formData.options} onChange={updateOptions} />
            {errors.options && <p className="text-red-500 text-sm">{errors.options}</p>}
        </div>
        <div className="flex items-center space-x-2">
            <Label className="bisheng-label">允许多选</Label>
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
            <Input
                className={`mt-2 ${errors.displayName ? "border-red-500" : ""}`}
                id="displayName"
                placeholder={namePlaceholders[formData.formType]}
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
            />
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
            <Label className="bisheng-label">允许上传多个文件</Label>
            <Switch
                checked={formData.isMultiple}
                onCheckedChange={(checked) => setFormData({ ...formData, isMultiple: checked })}
            />
        </div>

        <div>
            <Label className="flex items-center bisheng-label">
                临时知识库名称
                <QuestionTooltip content={'文件将会上传到以此命名的临时知识库中，可在文档知识库问答、助手等节点中使用'} />
            </Label>
            <Input
                className={`mt-2 ${errors.variableName ? "border-red-500" : ""}`}
                id="variableName"
                placeholder={t("enterVariableName")}
                value={formData.variableName}
                onChange={(e) => setFormData({ ...formData, variableName: e.target.value })}
            />
            {errors.variableName && <p className="text-red-500 text-sm">{errors.variableName}</p>}
        </div>
        {!formData.isMultiple && (
            <>
                <div>
                    <Label className="flex items-center bisheng-label">
                        文件内容变量名称
                        <QuestionTooltip content={'文件解析结果全文将会存储在此变量中，使用时请注意可能会超出模型上下文长度'} />
                    </Label>
                    <Input
                        className={`mt-2 ${errors.filecontent ? "border-red-500" : ""}`}
                        id="filecontent"
                        placeholder={t("enterVariableName")}
                        value={formData.filecontent}
                        onChange={(e) => setFormData({ ...formData, filecontent: e.target.value })}
                    />
                    {errors.filecontent && <p className="text-red-500 text-sm">{errors.filecontent}</p>}
                </div>

                <div>
                    <Label className="flex items-center bisheng-label">
                        文件路径变量名称
                        <QuestionTooltip content={'文件路径将会存储在此变量中，后续可在代码节点中使用'} />
                    </Label>
                    <Input
                        className={`mt-2 ${errors.filepath ? "border-red-500" : ""}`}
                        id="filepath"
                        placeholder={t("enterVariableName")}
                        value={formData.filepath}
                        onChange={(e) => setFormData({ ...formData, filepath: e.target.value })}
                    />
                    {errors.filepath && <p className="text-red-500 text-sm">{errors.filepath}</p>}
                </div>
            </>
        )}
    </div>;

    return (
        <form onSubmit={handleFormSubmit} className="space-y-4">
            <div>
                <Label className="bisheng-label">{t("formType")}</Label>
                <div className="flex gap-4 justify-between mx-6 mt-2">
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Text ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.Text)}
                    >
                        <Type size={18} />
                        {t("textInput")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Select ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.Select)}
                    >
                        <ChevronsDown size={18} />
                        {t("dropdown")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.File ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => handleChangeFormType(FormType.File)}
                    >
                        <CloudUpload size={18} />
                        {t("file")}
                    </Button>
                </div>
            </div>

            {formData.formType === FormType.Text && (InputForm)}
            {formData.formType === FormType.Select && (SelectForm)}
            {formData.formType === FormType.File && (FileForm)}

            <div className="flex space-x-4 justify-end">
                <Button className="px-8" type="button" variant="outline" onClick={onCancel}>
                    {t("cancel")}
                </Button>
                <Button className="px-8" type="submit">
                    {t("confirm")}
                </Button>
            </div>
        </form>
    );
}
export default function InputFormItem({ data, onChange, onValidate }) {
    const { t } = useTranslation('flow'); // 使用国际化
    const [isOpen, setIsOpen] = useState(false);
    const [editKey, setEditKey] = useState(""); // 控制编辑模式
    const [foucsUpdate, setFoucsUpdate] = useState(false);
    const [error, setError] = useState(false);

    // 打开弹窗并重置状态
    const handleOpen = () => {
        setEditKey(""); // 新建时不设置为编辑模式
        setIsOpen(true);
    };

    // 关闭弹窗
    const handleClose = () => {
        setIsOpen(false);
    };

    // 提交表单数据，添加或更新表单项
    const scrollRef = useRef(null);
    const handleSubmit = (_data) => {
        const {
            allowMultiple,
            isMultiple,
            displayName: value,
            formType: type,
            isRequired: required,
            options,
            variableName: key,
            filecontent: file_content,
            filepath: file_path,
        } = _data;

        const multiple = type === FormType.File ? isMultiple : allowMultiple;
        if (editKey) {
            // 编辑模式，更新表单项
            data.value = data.value.map((opt) =>
                opt.key === editKey
                    ? { key, type, value, required, multiple, options, file_content, file_path }
                    : opt
            );
        } else {
            // 新建模式，添加表单项
            data.value.push({
                key,
                type,
                value,
                required,
                multiple,
                file_content,
                file_path,
                options,
            });
            setTimeout(() => {
                scrollRef.current?.scrollTo(0, scrollRef.current?.scrollHeight); // 滚动到底部
            }, 0);
        }
        onChange(data.value);
        setFoucsUpdate(!foucsUpdate);
        setIsOpen(false); // 关闭弹窗
    };

    // 当编辑 DragOptions 中的表单项时打开弹窗
    const handleEditClick = (index, option) => {
        const item = data.value[index];
        setEditKey(item.key); // 设置为编辑模式
        setIsOpen(true); // 打开弹窗
    };

    // 更新 DragOptions 的顺序变化
    const handleOptionsChange = (newOptions) => {
        data.value = newOptions.map((el) => {
            return data.value.find((op) => op.key === el.key);
        });
        onChange(data.value);
    };

    // 校验逻辑
    useEffect(() => {
        onValidate(() => {
            if (!data.value.length) {
                setError(true);
                return t("atLeastOneFormItem"); // "至少添加一个表单项"
            }
            setError(false);
            return false;
        });

        return () => onValidate(() => { });
    }, [data.value]);

    return (
        <div className="node-item mb-4 nodrag" data-key={data.key}>
            {data.value.length > 0 && (
                <DragOptions
                    scroll
                    ref={scrollRef}
                    options={data.value.map((el) => ({
                        key: el.key,
                        text: el.type === FormType.File && !el.multiple ? `${el.value}(${el.key},${el.file_content},${el.file_path})` : `${el.value}(${el.key})`,
                        type: el.type,
                    }))}
                    onEditClick={handleEditClick} // 点击编辑时执行的逻辑
                    onChange={handleOptionsChange} // 拖拽排序后的更新
                />
            )}
            <Button
                onClick={handleOpen}
                variant="outline"
                className="border-primary text-primary mt-2"
            >
                {data.label}
            </Button>
            {error && <p className="text-red-500 text-sm">{t("atLeastOneFormItem")}</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>
                            {editKey ? t("editFormItem") : t("addFormItem")}
                        </DialogTitle>
                    </DialogHeader>

                    <Form
                        initialData={
                            editKey
                                ? data.value.find((el) => el.key === editKey)
                                : null
                        } // 如果是编辑模式，传入当前表单数据
                        onSubmit={handleSubmit} // 表单提交时回传数据给父组件
                        onCancel={handleClose} // 取消关闭弹窗
                        existingOptions={data.value} // 传递当前所有 options 以检查重复
                    />
                </DialogContent>
            </Dialog>
        </div>
    );
}