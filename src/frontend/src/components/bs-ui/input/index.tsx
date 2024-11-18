import { CircleMinus, Eye, EyeOff } from "lucide-react"
import * as React from "react"
import { useState } from "react"
import { SearchIcon } from "../../bs-icons/search"
import { cname, generateUUID } from "../utils"

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> { }

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, boxClassName, type, maxLength, value, defaultValue, onChange, ...props }, ref) => {
        // 用于存储当前的输入值
        const [currentValue, setCurrentValue] = useState(value || defaultValue || '');

        // 处理 onChange 事件，更新 currentValue
        const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
            setCurrentValue(e.target.value);
            if (onChange) {
                onChange(e); // 如果外部有 onChange，依然需要调用它
            }
        };

        // 当 value 或 defaultValue 改变时更新 currentValue
        React.useEffect(() => {
            if (value !== undefined) {
                setCurrentValue(value);
            }
        }, [value]);

        const noEmptyProps =
            value === undefined ? {} : { value: currentValue }

        return (
            <div className={cname("relative w-full", boxClassName)}>
                <input
                    type={type}
                    className={cname(
                        "flex h-9 w-full rounded-md border border-input bg-search-input px-3 py-1 text-sm text-[#111] dark:text-gray-50 shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                        className
                    )}
                    defaultValue={defaultValue}
                    onChange={handleChange}
                    maxLength={maxLength}
                    ref={ref}
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
    value?: string[],
    inputClassName?: string,
    className?: string,
    defaultValue?: string[],
    onChange?: (values: string[]) => void
}>(
    ({ rules = [], className, inputClassName, value = [], defaultValue = [], ...props }, ref) => {
        // 初始化 inputs 状态，为每个值分配唯一 ID
        const [inputs, setInputs] = React.useState(() =>
            value.map(val => ({ id: generateUUID(8), value: val }))
        );

        React.useEffect(() => {
            // 仅为新增的值分配新的 ID
            const updatedInputs = value.map((val, index) => {
                return inputs[index] && inputs[index].value === val
                    ? inputs[index] // 如果当前输入项与外部值相同，则保持不变
                    : { id: generateUUID(8), value: val }; // 否则，创建新的输入项
            });
            setInputs(updatedInputs);
        }, [value]); // 依赖项中包含 value，确保外部 value 更新时同步更新


        const handleChange = (newValue, id, index) => {
            let newInputs = inputs.map(input =>
                input.id === id ? { ...input, value: newValue } : input
            );
            // push
            if (index === newInputs.length - 1) {
                newInputs = ([...newInputs, { id: generateUUID(8), value: '' }]);
            }
            setInputs(newInputs);
            props.onChange(newInputs.map(input => input.value));
        };

        // delete input
        const handleRemoveInput = (id) => {
            const newInputs = inputs.filter(input => input.id !== id);
            setInputs(newInputs);
            props.onChange(newInputs.map(input => input.value));
        };

        return <div className={cname('', className)}>
            {
                inputs.map((item, index) => (
                    <div className="relative mb-2">
                        <Input
                            key={item.id}
                            defaultValue={item.value}
                            className={cname('pr-8', inputClassName)}
                            placeholder={props.placeholder || ''}
                            onChange={(e) => handleChange(e.target.value, item.id, index)}
                            onInput={(e) => {
                                rules.some(rule => {
                                    if (rule.maxLength && e.target.value.length > rule.maxLength) {
                                        e.target.nextSibling.textContent = rule.message;
                                        e.target.nextSibling.style.display = '';
                                        return true;
                                    }
                                    if (e.target.nextSibling) {
                                        e.target.nextSibling.style.display = 'none';
                                    }
                                })
                            }}
                        // onFocus={(e) => {
                        //     if (e.target.value && index === inputs.length - 1) {
                        //         setInputs([...inputs, { id: generateUUID(8), value: '' }]);
                        //     }
                        // }}
                        ></Input>
                        <p className="text-sm text-red-500" style={{ display: 'none' }}></p>
                        {index !== inputs.length - 1 && <CircleMinus
                            onClick={(e) => {
                                if (e.target.previousSibling) {
                                    e.target.previousSibling.style.display = 'none';
                                }
                                handleRemoveInput(item.id)
                            }} className="w-4 h-4 absolute top-2.5 right-2 text-gray-500 hover:text-gray-700 cursor-pointer" />}
                    </div>
                ))
            }
        </div>
    }
)

export { Input, InputList, PasswordInput, SearchInput, Textarea }
