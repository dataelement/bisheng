import { Slider } from '@/components/bs-ui/slider';
import { Switch } from '@/components/bs-ui/switch';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger
} from '@/components/bs-ui/tooltip';
import { useModel } from '@/pages/ModelPage/manage';
import { ModelSelect } from '@/pages/ModelPage/manage/tabs/WorkbenchModel';
import { WorkflowNodeParam } from '@/types/flow';
import { HelpCircle } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import InputItem from './InputItem';
import { useTranslation } from 'react-i18next';

interface RerankModel {
    value: string;
    label: string;
}

/**
 * 检索配置组件
 * 包含权限校验、开关控制、权重调整和结果设置
 */
interface RetrievalConfigProps {
    data: WorkflowNodeParam;
    onChange: (value: any) => void;
    onValidate?: (validate: () => string | false) => void;
}

const RetrievalConfig: React.FC<RetrievalConfigProps> = ({ data, onChange, onValidate, i18nPrefix }) => {
    const { t } = useTranslation('flow'); // 使用国际化
    const [keywordWeight, setKeywordWeight] = useState(data.value?.keyword_weight ?? 0.5);
    const [vectorWeight, setVectorWeight] = useState(1 - (data.value?.keyword_weight ?? 0.5));
    const [searchSwitch, setSearchSwitch] = useState(data.value?.search_switch ?? false);
    const [rerankEnabled, setRerankEnabled] = useState(data.value?.rerank_flag ?? false);
    const [selectedRerankModel, setSelectedRerankModel] = useState(data.value?.rerank_model || '');
    const [resultLength, setResultLength] = useState(data.value?.max_chunk_size || 15000);
    const [userAuth, setUserAuth] = useState(data.value?.user_auth ?? false);
    const { rerank } = useModel();

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
        if (searchSwitch && rerankEnabled) {
            onValidate(() => {
                if (!selectedRerankModel) {
                    return t('rerankModelCannotBeEmpty');
                }
                return false;
            });
        } else {
            onValidate(() => false);
        }
        return () => onValidate(() => false);
    }, [searchSwitch, rerankEnabled, selectedRerankModel, onValidate]);

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

    const handleSliderChange = (value: number[]) => {
        const newKeywordWeight = value[0];
        const newVectorWeight = 1.0 - newKeywordWeight;

        setKeywordWeight(newKeywordWeight);
        setVectorWeight(newVectorWeight);
    };

    const handleSearchToggle = (checked: boolean) => {
        setSearchSwitch(checked);
    };

    return (
        <div className="space-y-2 rounded-lg mb-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-500">{t(`${i18nPrefix}label`)}</span>
                </div>
                <Switch
                    checked={searchSwitch}
                    onCheckedChange={handleSearchToggle}
                />
            </div>

            {searchSwitch && (
                <div className="flex items-center justify-between pl-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-500">{t('userAuthVerification')}</span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">{t('enableToVerifyUserAccessToKnowledgeBase')}</p>
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

            {searchSwitch && (
                <div className="space-y-4 pl-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-500">{t('retrieverWeightSettings')}</span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">{t('adjustWeightForVectorOrKeywordSearch')}</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center gap-3">
                            <div className="flex flex-col items-start w-12">
                                <span className="text-xs font-medium text-gray-600">{t('keyword')}</span>
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
                                <span className="text-xs font-medium text-gray-600">{t('vector')}</span>
                                <span className="text-xs text-gray-500">{vectorWeight.toFixed(2)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {searchSwitch && (
                <div className="flex items-center justify-between pl-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-500">{t('retrievalResultReRank')}</span>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">{t('useRerankModelForReorderingResults')}</p>
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

            {rerankEnabled && searchSwitch && (
                <div className="pl-4">
                    <ModelSelect
                        close
                        label=""
                        placeholder={t('selectRerankModel')}
                        value={selectedRerankModel}
                        options={rerank}
                        onChange={(val) => setSelectedRerankModel(val)}
                    />
                </div>
            )}

            {searchSwitch && (
                <div className="space-y-2 pl-4">
                    <div className="flex items-center gap-2">
                        <label className="text-sm font-medium text-gray-500">{t('retrievalResultLength')}</label>
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <HelpCircle className="h-4 w-4 text-gray-400 cursor-pointer" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p className="max-w-xs">{t('controlResultTextLengthForModel')}</p>
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
