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

function Form({ initialData, onSubmit, onCancel, existingOptions }) {
    const { t } = useTranslation('flow'); // 使用国际化
    const namePlaceholders = {
        [FormType.Text]: t("nameExample"), // 例如“姓名”
        [FormType.Select]: t("categoryExample"), // 例如“保险类别”
        [FormType.File]: t("uploadExample"), // 例如“请上传去年财报”
    };

    const [formData, setFormData] = useState({
        formType: FormType.Text,
        displayName: "",
        variableName: "",
        isRequired: true,
        allowMultiple: false,  // 允许多选开关
        options: [],  // 选项，适用于下拉框
    });
    const [errors, setErrors] = useState<any>({});

    const oldVarNameRef = useRef("");
    useEffect(() => {
        if (initialData) {
            const {
                type: formType,
                value: displayName,
                key: variableName,
                required: isRequired,
                multi: allowMultiple,
                options = [] } = initialData;
            setFormData({
                formType,
                displayName,
                variableName,
                isRequired,
                allowMultiple,
                options,
            });

            oldVarNameRef.current = variableName;
        }
    }, [initialData]);

    useEffect(() => {
        if (initialData) return
        // 初始化变量名
        const names = {
            [FormType.Text]: "text_input",
            [FormType.Select]: "category",
            [FormType.File]: "file",
        }
        let initialVarName = names[formData.formType];
        let counter = 1;
        while (existingOptions?.some(opt => opt.key === initialVarName)) {
            counter += 1;
            initialVarName = `${names[formData.formType]}${counter}`;
        }
        setFormData((prevData) => ({
            ...prevData,
            variableName: initialVarName,
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

    return (
        <form onSubmit={handleFormSubmit} className="space-y-4">
            <div>
                <Label className="bisheng-label">{t("formType")}</Label>
                <div className="flex gap-4 justify-between mx-6 mt-2">
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Text ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.Text })}
                    >
                        <Type size={18} />
                        {t("textInput")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.Select ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.Select })}
                    >
                        <ChevronsDown size={18} />
                        {t("dropdown")}
                    </Button>
                    <Button
                        className={`flex flex-col h-18 w-28 ${formData.formType === FormType.File ? "border-primary/40 bg-[#DFE9FD] text-primary" : ""}`}
                        type="button"
                        variant="outline"
                        onClick={() => setFormData({ ...formData, formType: FormType.File })}
                    >
                        <CloudUpload size={18} />
                        {t("file")}
                    </Button>
                </div>
            </div>

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

            {formData.formType === FormType.Select && (
                <div>
                    <Label className="bisheng-label">{t("options")}</Label>
                    <DragOptions scroll options={formData.options} onChange={updateOptions} />
                    {errors.options && <p className="text-red-500 text-sm">{errors.options}</p>}
                </div>
            )}

            {/* {formData.formType === FormType.Select && (
                <div className="flex items-center space-x-2">
                    <Label className="bisheng-label">允许多选</Label>
                    <Switch
                        checked={formData.allowMultiple}
                        onCheckedChange={(checked) => setFormData({ ...formData, allowMultiple: checked })}
                    />
                </div>
            )} */}

            <div className="flex items-center space-x-2">
                <Label className="bisheng-label">是否必填</Label>
                <Switch
                    checked={formData.isRequired}
                    onCheckedChange={(checked) => setFormData({ ...formData, isRequired: checked })}
                />
            </div>

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
    const handleSubmit = (_data) => {
        const {
            allowMultiple: multi,
            displayName: value,
            formType: type,
            isRequired: required,
            options,
            variableName: key,
        } = _data;

        if (editKey) {
            // 编辑模式，更新表单项
            data.value = data.value.map((opt) =>
                opt.key === editKey
                    ? { key, type, value, required, multi, options }
                    : opt
            );
        } else {
            // 新建模式，添加表单项
            data.value.push({
                key,
                type,
                value,
                required,
                multi,
                options,
            });
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
                    options={data.value.map((el) => ({
                        key: el.key,
                        text: `${el.value}(${el.key})`,
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