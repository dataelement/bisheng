import { CircleMinus, CirclePlus, Eye, EyeOff } from "lucide-react"
import * as React from "react"
import { useState } from "react"
import { SearchIcon } from "../../bs-icons/search"
import { cname, generateUUID } from "../utils"

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> {
    boxClassName?: string;    // 外层容器的 className
    showCount?: boolean;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, boxClassName, type, maxLength, showCount, value, defaultValue, onChange, ...props }, ref) => {
        const [currentValue, setCurrentValue] = useState(value ?? defaultValue ?? '');

        const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
            const { value } = e.target;
            if (type === "number") {
                // 使用正则表达式精确阻止负数（包括粘贴操作）
                if (/-/.test(value)) return;

                // 阻止单独的0
                if (props.min > 0 && value === "0") return;

                // 最大长度限制
                if (maxLength && value.length > maxLength) return;
                // 最大值限制
                if (props.max && value > props.max) return
            }

            setCurrentValue(value);
            if (onChange) {
                onChange(e);
            }
        };

        // 处理粘贴事件
        const handlePaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
            if (type === "number") {
                const pasteData = e.clipboardData.getData('text/plain');
                // 阻止包含负数的粘贴
                if (/-/.test(pasteData)) {
                    e.preventDefault();
                }
            }
        };

        React.useEffect(() => {
            if (value !== undefined) {
                // 处理外部传入值为0的情况
                if (type === "number" && (value === 0 || value === "0")) {
                    // setCurrentValue('');
                } else {
                    setCurrentValue(value);
                }
            }
        }, [value, type]);

        const noEmptyProps =
            value === undefined ? {} : { value: currentValue }

        return (
            <div className={cname("relative w-full", boxClassName)}>
                <input
                    type={type}
                    className={cname(
                        "flex h-9 w-full rounded-md border border-input bg-search-input px-3 py-1 text-sm text-[#111] dark:text-gray-50 shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                        type === 'number' ? 'number-input-arrows' : '',
                        className
                    )}
                    defaultValue={defaultValue}
                    onChange={handleChange}
                    onPaste={handlePaste} // 添加粘贴事件处理
                    maxLength={maxLength}
                    ref={ref}
                    {...noEmptyProps}
                    {...props}
                />
                {showCount && maxLength && (
                    <div className="absolute right-1 bottom-1 text-xs text-gray-400 dark:text-gray-500">
                        {currentValue.length}/{maxLength}
                    </div>
                )}

                <style jsx>{`
                    .number-input-arrows::-webkit-inner-spin-button,
                    .number-input-arrows::-webkit-outer-spin-button {
                        opacity: 1;
                    }
                `}</style>
            </div>
        );
    }
);
Input.displayName = "Input"


const SearchInput = React.forwardRef<HTMLInputElement, InputProps & { inputClassName?: string, iconClassName?: string }>(
    ({ className, inputClassName, iconClassName, ...props }, ref) => {
        return <div className={cname("relative", className)}>
            <SearchIcon className={cname("h-5 w-5 absolute left-2 top-2 text-gray-950 dark:text-gray-500 z-10", iconClassName)} />
            <Input type="text" ref={ref} className={cname("pl-8 bg-search-input", inputClassName)} {...props}></Input>
        </div>
    }
)

SearchInput.displayName = "SearchInput"


const PasswordInput = React.forwardRef<HTMLInputElement, InputProps & { inputClassName?: string, iconClassName?: string }>(
    ({ className, inputClassName, iconClassName, ...props }, ref) => {
        const [type, setType] = useState('password')
        const handleShowPwd = () => {
            type === 'password' ? setType('text') : setType('password')
        }
        return <div className={cname("relative flex place-items-center", className)}>
            <Input type={type} ref={ref} className={cname("pr-8 bg-search-input", inputClassName)} {...props}></Input>
            {
                type === 'password'
                    ? <EyeOff onClick={handleShowPwd} className={cname("size-4 absolute right-2 text-gray-950 dark:text-gray-500 cursor-pointer", iconClassName)} />
                    : <Eye onClick={handleShowPwd} className={cname("size-4 absolute right-2 text-gray-950 dark:text-gray-500 cursor-pointer", iconClassName)} />
            }
        </div>
    }
)

PasswordInput.displayName = 'PasswordInput'


/**
 * 多行文本
 */
export interface TextareaProps
    extends React.TextareaHTMLAttributes<HTMLTextAreaElement> { }

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps & { boxClassName?: string }>(
    ({ className, boxClassName = '', maxLength, value, defaultValue, onChange, ...props }, ref) => {
        // 用于存储当前的输入值
        const [currentValue, setCurrentValue] = useState(value || defaultValue || '');

        // 处理 onChange 事件，更新 currentValue
        const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
            if (onChange) {
                onChange(e);
            }
            if (value === undefined && defaultValue === undefined) return
            setCurrentValue(e.target.value);
        };

        // 当 value 或 defaultValue 改变时更新 currentValue
        React.useEffect(() => {
            if (value !== undefined) {
                setCurrentValue(value || '');
            }
        }, [value]);

        const noEmptyProps =
            value === undefined ? {} : { value: currentValue }

        return (
            <div className={cname('relative w-full', boxClassName)}>
                <textarea
                    className={cname(
                        "flex min-h-[80px] w-full rounded-md border border-input bg-search-input px-3 py-2 text-sm text-[#111] dark:text-gray-50 shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                        className
                    )}
                    ref={ref}
                    defaultValue={defaultValue}
                    maxLength={maxLength}
                    onChange={handleChange}
                    {...noEmptyProps}
                    {...props}
                />
                {maxLength && (
                    <div className="absolute right-1 bottom-1 text-xs text-gray-400 dark:text-gray-500">
                        {currentValue.length}/{maxLength}
                    </div>
                )}
            </div>
        );
    }
);
Textarea.displayName = "Textarea"


/**
 * input list
 */
const InputList = React.forwardRef<HTMLDivElement, InputProps & {
    rules?: any[],
    dict?: boolean, // value 数据结构类型
    value?: string[],
    inputClassName?: string,
    className?: string,
    defaultValue?: string[],
    onChange?: (values: string[]) => void
}>(
    ({ rules = [], className, dict = false, inputClassName, value = [], defaultValue = [], ...props }, ref) => {
        // 初始化 inputs 状态，为每个值分配唯一 ID
        const [inputs, setInputs] = React.useState(() =>
            dict ? value : value.map(val => ({ key: generateUUID(6), value: val }))
        );

        React.useEffect(() => {
            if (dict) return
            // 仅为新增的值分配新的 ID
            const updatedInputs = value.map((val, index) => {
                return inputs[index] && inputs[index].value === val
                    ? inputs[index] // 如果当前输入项与外部值相同，则保持不变
                    : { key: generateUUID(6), value: val }; // 否则，创建新的输入项
            });
            setInputs(updatedInputs);
        }, [dict, value]); // 依赖项中包含 value，确保外部 value 更新时同步更新


        const handleChange = (newValue, id, index) => {
            let newInputs = inputs.map(input =>
                input.key === id ? { ...input, value: newValue } : input
            );
            // push
            if (index === newInputs.length - 1) {
                newInputs = ([...newInputs, { key: generateUUID(6), value: '' }]);
            }
            setInputs(newInputs);
            props.onChange(dict ? newInputs : newInputs.map(input => input.value));
        };

        // delete input
        const handleRemoveInput = (id) => {
            const newInputs = inputs.filter(input => input.key !== id);
            setInputs(newInputs);
            props.onChange(dict ? newInputs : newInputs.map(input => input.value));
        };

        return <div className={cname('', className)}>
            {
                inputs.map((item, index) => (
                    <div className="relative mb-2">
                        <Input
                            key={item.key}
                            defaultValue={item.value}
                            className={cname('pr-8', inputClassName)}
                            placeholder={props.placeholder || ''}
                            onChange={(e) => handleChange(e.target.value, item.key, index)}
                            // onInput={(e) => {
                            //     rules.some(rule => {
                            //         if (rule.maxLength && e.target.value.length > rule.maxLength) {
                            //             e.target.parentNode.nextSibling.textContent = rule.message;
                            //             e.target.parentNode.nextSibling.style.display = '';
                            //             return true;
                            //         }
                            //         if (e.target.nextSibling) {
                            //             e.target.parentNode.nextSibling.style.display = 'none';
                            //         }
                            //     })
                            // }}
                        // onFocus={(e) => {
                        //     if (e.target.value && index === inputs.length - 1) {
                        //         setInputs([...inputs, { id: generateUUID(8), value: '' }]);
                        //     }
                        // }}
                        ></Input>
                        <p className="text-sm text-red-500" style={{ display: 'none' }}></p>
                        {index === inputs.length - 1 ? <CirclePlus className="w-4 h-4 absolute top-2.5 right-2 text-gray-500 hover:text-gray-700 cursor-pointer"
                            onClick={() => {
                                const newInputs = [...inputs, { key: generateUUID(6), value: '' }]
                                setInputs(newInputs);
                                props.onChange(newInputs.map(input => input.value));
                            }} /> : <CircleMinus
                            onClick={(e) => {
                                if (e.target.previousSibling) {
                                    e.target.previousSibling.style.display = 'none';
                                }
                                handleRemoveInput(item.key)
                            }} className="w-4 h-4 absolute top-2.5 right-2 text-gray-500 hover:text-gray-700 cursor-pointer" />}
                    </div>
                ))
            }
        </div>
    }
)

export { Input, InputList, PasswordInput, SearchInput, Textarea }
