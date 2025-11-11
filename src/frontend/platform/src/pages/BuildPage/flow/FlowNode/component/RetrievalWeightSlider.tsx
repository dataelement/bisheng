import { Input } from '@/components/bs-ui/input';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from '@/components/bs-ui/select';
import { Slider } from '@/components/bs-ui/slider';
import { Switch } from '@/components/bs-ui/switch';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from '@/components/bs-ui/tooltip';
import { WorkflowNodeParam } from '@/types/flow';
import { HelpCircle } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import InputItem from './InputItem';
import { useModel } from '@/pages/ModelPage/manage';
import { ModelSelect } from '@/pages/ModelPage/manage/tabs/WorkbenchModel';
import { t } from 'i18next';

// 重排模型类型定义
interface RerankModel {
    value: string;
    label: string;
}

/**
 * 检索配置组件
 * 包含权限校验、开关控制、权重调整和结果设置
 */
/**
 * 高级检索配置 Props
 * @property {WorkflowNodeParam} data 表单项数据
 * @property {(value: any) => void} onChange 值变更回调
 * @property {(validate: () => string | false) => void} [onValidate] 绑定校验回调
 */
interface RetrievalConfigProps {
    data: WorkflowNodeParam;
    onChange: (value: any) => void;
    onValidate?: (validate: () => string | false) => void;
}

/**
 * 高级检索配置组件
 * 兼容老版本仅包含 `user_auth` 与 `max_chunk_size` 的数据结构。
 */
const RetrievalConfig: React.FC<RetrievalConfigProps> = ({ data, onChange, onValidate }) => {

    // 初始化状态值，将原retrievalEnabled改为search_switch
    const [keywordWeight, setKeywordWeight] = useState( data.value?.keyword_weight ?? 0.5);
    const [vectorWeight, setVectorWeight] = useState(1 - (data.value?.keyword_weight ?? 0.5));
    const [searchSwitch, setSearchSwitch] = useState(data.value?.search_switch ?? false);
    const [rerankEnabled, setRerankEnabled] = useState(data.value?.rerank_flag ?? false);
    const [selectedRerankModel, setSelectedRerankModel] = useState(data.value?.rerank_model || '');
    const [resultLength, setResultLength] = useState(data.value?.max_chunk_size || 15000);
    const [userAuth, setUserAuth] = useState(data.value?.user_auth ?? false);
    const { rerank } = useModel();
    const [rerankError, setRerankError] = useState(false);

    // 确保权重和为1
    useEffect(() => {
        const total = keywordWeight + vectorWeight;
        if (Math.abs(total - 1.0) > 0.001) {
            const normalizedKeyword = keywordWeight / total;
            const normalizedVector = vectorWeight / total;
            setKeywordWeight(normalizedKeyword);
            setVectorWeight(normalizedVector);
        }
    }, [keywordWeight, vectorWeight]);
    useEffect(() => {
             // 仅当检索开关和重排开关都打开时，才校验模型是否选择
               if (searchSwitch && rerankEnabled) {
                  onValidate(() => {
                      // 若未选择模型，标记错误并返回提示信息
                      if (!selectedRerankModel) {
                          setRerankError(true);
                          return '请选择重排模型'; // 可替换为i18n翻译文本
                       }
                      // 校验通过
                      setRerankError(false);
                      return false;
                  });
           } else {
                  // 开关关闭时，清除校验错误
                  setRerankError(false);
                  onValidate(() => false);
              }
        
              // 组件卸载或依赖变化时清除校验
              return () => onValidate(() => false);
          }, [searchSwitch, rerankEnabled, selectedRerankModel, onValidate]);
    // 通知父组件值变化
    useEffect(() => {
        if (searchSwitch) {
            onChange({
                keyword_weight: keywordWeight,
                vector_weight: vectorWeight,
                user_auth: userAuth,
                search_switch: searchSwitch,
                rerank_flag: rerankEnabled,
                rerank_model: selectedRerankModel,
                max_chunk_size: resultLength,
            });
        } else {
            onChange({
                keyword_weight: 0.5,
                vector_weight: 0.5,
                user_auth: false,
                search_switch: false,
                rerank_flag: false,
                rerank_model: '',
                max_chunk_size: 15000,
            });
        }
    }, [
        keywordWeight,
        vectorWeight,
        searchSwitch,
        rerankEnabled,
        selectedRerankModel,
        resultLength,
        userAuth
    ]);

    // 处理权重滑块变化
    const handleSliderChange = (value: number[]) => {
        const newKeywordWeight = value[0];
        const newVectorWeight = 1.0 - newKeywordWeight;

        setKeywordWeight(newKeywordWeight);
        setVectorWeight(newVectorWeight);
    };

    // 处理检索开关变化（键名变更）
    const handleSearchToggle = (checked: boolean) => {
        setSearchSwitch(checked);
    };

    // 处理结果长度变化
    const handleResultLengthChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = parseInt(e.target.value, 10);
        if (!isNaN(value) && value > 0) {
            setResultLength(value);
        }
    };

    return (
        <div className="space-y-2 rounded-lg mb-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-500">高级检索设置</span>
                </div>
                <Switch
                    checked={searchSwitch}
                    onCheckedChange={handleSearchToggle}
                />
            </div>

            {/* 用户知识库权限校验 - 绑定到user_auth */}
            {searchSwitch && (
                <div className="flex items-center justify-between pl-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-500">用户知识库权限校验</span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">开启后将验证用户对知识库的访问权限</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <Switch
                        checked={userAuth}
                        onCheckedChange={setUserAuth}
                    />
                </div>
            )}

            {/* 检索器权重设置（仅在检索开启时显示） */}
            {searchSwitch && (
                <div className="space-y-4 pl-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-500">检索器权重设置</span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">通过调整权重，确定优先使用向量检索还是优先使用关键词检索。</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center gap-3">
                            <div className="flex flex-col items-start w-12">
                                <span className="text-xs font-medium text-gray-600">关键词</span>
                                <span className="text-xs text-gray-500">{keywordWeight.toFixed(2)}</span>
                            </div>

                            <div className="flex-1 px-0">
                                <Slider
                                    value={[keywordWeight]}
                                    onValueChange={handleSliderChange}
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    className="w-full"
                                />
                            </div>

                            <div className="flex flex-col items-end w-12">
                                <span className="text-xs font-medium text-gray-600">向量</span>
                                <span className="text-xs text-gray-500">{vectorWeight.toFixed(2)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* 检索结果重排 */}
            {searchSwitch && (
                <div className="flex items-center justify-between pl-4">
                    <div className="flex items-center gap-2">
                      
                        <span className="text-sm font-medium text-gray-500">
                            <span className='text-red-500'>*</span>
                            检索结果重排
                        </span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">开启后，将使用重排模型对检索结果进行二次排序</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <Switch
                        checked={rerankEnabled}
                        onCheckedChange={setRerankEnabled}
                        disabled={!searchSwitch}
                    />
                </div>
            )}

            {/* 重排模型选择（仅在重排开启时显示） */}
            {rerankEnabled && searchSwitch && (
            <div className="pl-4">
                <ModelSelect
                close
                label="重排模型"
                 placeholder="请选择重排模型"
                value={selectedRerankModel}
                options={rerank}
                onChange={(val) => setSelectedRerankModel(val)}
                />
            </div>
            )}

            {/* 检索结果长度 */}
            {searchSwitch && (
                <div className="space-y-2 pl-4">
                    <div className="flex items-center gap-2">
                        <label className="text-sm font-medium text-gray-500">检索结果长度</label>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">通过此参数控制最终传给模型的知识库检索结果文本长度，超过模型支持的最大上下文长度可能会导致报错。</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <InputItem
                        type="number"
                        linefeed
                        data={{
                            min: 0,
                            value: resultLength,
                            label: '' // 标签已在上方单独显示，此处留空
                        }}
                        onChange={(value) => setResultLength(Number(value))}
                    />
                </div>
            )}
        </div>
    );
};

export default RetrievalConfig;