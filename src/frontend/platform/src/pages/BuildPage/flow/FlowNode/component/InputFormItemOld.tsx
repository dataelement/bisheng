// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { Dialog,DialogContent,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";
import { isVarInFlow } from "@/util/flowUtils";
import { cloneDeep } from "lodash-es";
import { useEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化
import useFlowStore from "../../flowStore";
import DragOptions from "./DragOptions";

import { LegacyInputFormEditor as Form } from "./LegacyInputFormEditor";
import { FormType } from "./inputFormTypes";
export default function InputFormItem({ data, nodeId, onChange, onValidate, onVarEvent, i18nPrefix }) {
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
            fileType: file_type,
            fileContentSize: file_content_size,
            imageFile: image_file
        } = _data;

        const multiple = type === FormType.File ? isMultiple : allowMultiple;
        if (editKey) {
            // 编辑模式，更新表单项
            data.value = data.value.map((opt) =>
                opt.key === editKey
                    ? {
                        key,
                        type,
                        value,
                        required,
                        multiple,
                        options,
                        file_content,
                        file_path,
                        file_type,
                        file_content_size,
                        image_file
                    }
                    : opt
            );
        } else {
            // 新建模式，添加表单项
            data.value = [...data.value, {
                key,
                type,
                value,
                required,
                multiple,
                file_content,
                file_path,
                file_type,
                options,
                file_content_size,
                image_file
            }];
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

    const options = useMemo(() => {
        const _options = cloneDeep(data.value)
        return _options.map((el) => {
            // cn
            if (el.type === 'text') {
                el.value = el.value.replace(/{{#(.*?)#}}/g, (a, key) => {
                    return data.varZh?.[key] || key;
                })
            }

            return {
                key: el.key,
                text: el.type === 'file' ? `${el.value}(${el.key},${el.file_content},${el.file_path})` : `${el.value}(${el.key})`,
                type: el.type,
            }
        });
    }, [data.value])

    const { flow } = useFlowStore();
    // 校验变量是否可用
    const validateVarAvailble = () => {
        const errors = data.value.reduce((acc, value) => {
            if (value.type === 'text') {
                value.value.replace(/{{#(.*?)#}}/g, (a, part) => {
                    const _error = isVarInFlow(nodeId, flow.nodes, part, data.varZh?.[part])
                    _error && acc.push(_error)
                })
            }
            return acc
        }, [])
        return Promise.resolve(errors);
    };

    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [data]);

    return (
        <div className="node-item mb-4 nodrag" data-key={data.key}>
            {data.value.length > 0 && (
                <DragOptions
                    scroll
                    ref={scrollRef}
                    options={options}
                    onEditClick={handleEditClick} // 点击编辑时执行的逻辑
                    onChange={handleOptionsChange} // 拖拽排序后的更新
                />
            )}
            <Button onClick={handleOpen} variant="outlined" className="border-primary text-primary mt-2" color="default">
                {t(`${i18nPrefix}label`)}
            </Button>
            {error && <p className="text-red-500 text-sm">{t("atLeastOneFormItem")}</p>}

            <Dialog open={isOpen} onOpenChange={setIsOpen}>
                <DialogContent className="max-h-screen overflow-auto">
                    <DialogHeader>
                        <DialogTitle>
                            {editKey ? t("editFormItem") : t("addFormItem")}
                        </DialogTitle>
                    </DialogHeader>

                    {isOpen && <Form
                        nodeId={nodeId}
                        nodeData={data}
                        initialData={
                            editKey
                                ? data.value.find((el) => el.key === editKey)
                                : null
                        } // 如果是编辑模式，传入当前表单数据
                        onSubmit={handleSubmit} // 表单提交时回传数据给父组件
                        onCancel={handleClose} // 取消关闭弹窗
                        existingOptions={data.value} // 传递当前所有 options 以检查重复
                    />
                    }
                </DialogContent>
            </Dialog>
        </div>
    );
}