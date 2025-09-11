import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { rebUploadFile, retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import FileUploadStep2 from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";
import PreviewResult from "./components/PreviewResult";
import { LoadingIcon } from "@/components/bs-icons/loading";

// 调整模式固定步骤标签（3步）
const AdjustStepLabels = [
  '分段策略',
  '原文对比',
  '数据处理'
];

export default function AdjustFilesUpload() {
  const { t } = useTranslation('knowledge');
  const navigate = useNavigate();
  const location = useLocation();
  const { message } = useToast();
  const { fileId: knowledgeId } = useParams(); 
  
  // 从路由状态获取调整模式的初始数据（必须传文件数据）
  const initFileData = location.state?.fileData;
  if (!initFileData) {
    navigate(-1); // 无数据时回退
    return null;
  }
{console.log(initFileData,123)}
  // 调整模式专属状态
  const [currentStep, setCurrentStep] = useState(1);
    const getParsedSplitRule = (rawSplitRule) => {
    // 处理无 split_rule 或为空的情况
    if (!rawSplitRule) {
      return {
        knowledge_id: "",
        separator: ["\\n\\n", "\\n"],
        separator_rule: ["after", "after"],
        chunk_size: 1000,
        chunk_overlap: 100,
        retain_images: false,
        force_ocr: true,
        enable_formula: true,
        filter_page_header_footer: false,
        excel_rule: {
          slice_length: 10,
          append_header: true,
          header_start_row: 1,
          header_end_row: 1
        }
      };
    }

    try {
      // 解析 JSON 字符串
      const parsed = JSON.parse(rawSplitRule);
      // 格式适配：统一字段格式，避免子组件处理
      return {
        knowledge_id: parsed.knowledge_id || "", // 知识库ID
        // 分隔符：确保是数组，默认双换行+单换行
        separator: Array.isArray(parsed.separator) ? parsed.separator : ["\\n\\n", "\\n"],
        // 分隔符规则：确保与 separator 长度一致，默认 after
        separator_rule: Array.isArray(parsed.separator_rule) 
          ? parsed.separator_rule 
          : ["after", "after"],
        // chunk大小：数字转字符串（子组件用字符串格式），默认1000
        chunk_size: parsed.chunk_size || 1000,
        // 重叠大小：默认100
        chunk_overlap: parsed.chunk_overlap || 100,
        // 布尔值转换：0→false，1→true，默认false
        retain_images: parsed.retain_images === 1,
        force_ocr: parsed.force_ocr === 1,
        enable_formula: parsed.enable_formula === 1,
        filter_page_header_footer: parsed.filter_page_header_footer === 1,
        // 表格规则：默认值兜底
        excel_rule: {
          slice_length: parsed.excel_rule?.slice_length || 10,
          append_header: parsed.excel_rule?.append_header === 1,
          header_start_row: parsed.excel_rule?.header_start_row || 1,
          header_end_row: parsed.excel_rule?.header_end_row || 1
        }
      };
    } catch (error) {
      // 解析失败时返回默认配置，避免崩溃
      console.error("split_rule 解析失败：", error);
      return {
        knowledge_id: "",
        separator: ["\\n\\n", "\\n"],
        separator_rule: ["after", "after"],
        chunk_size: 1000,
        chunk_overlap: 100,
        retain_images: false,
        force_ocr: true,
        enable_formula: true,
        filter_page_header_footer: false,
        excel_rule: {
          slice_length: 10,
          append_header: true,
          header_start_row: 1,
          header_end_row: 1
        }
      };
    }
  };
    const fileName = initFileData.name || initFileData.file_name || '';
  const fileSuffix = fileName.split('.').pop()?.toLowerCase() || 'txt';
  const fileType = ['xlsx', 'xls', 'csv'].includes(fileSuffix) ? 'table' : 'file';
  
  const [resultFiles, setResultFiles] = useState([
    {
      id: initFileData.id,
      fileName: initFileData.name || initFileData.file_name, // 兼容字段名
      file_path: initFileData.filePath || initFileData.object_name, // 兼容文件路径
      suffix: initFileData.suffix || initFileData.file_name?.split(".").pop() || "", // 解析后缀
      previewUrl:initFileData.previewUrl,
      fileType: fileType,
      split_rule: getParsedSplitRule(initFileData.split_rule) // 传入转换后的配置对象
    }
  ]);
  
  const [segmentRules, setSegmentRules] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isNextDisabled, setIsNextDisabled] = useState(false);
  const [repeatFiles, setRepeatFiles] = useState([]);
  const [retryLoad, setRetryLoad] = useState(false);

  // Ref管理
  const fileUploadStep2Ref = useRef(null);
  const _tempConfigRef = useRef({});
  const submittingRef = useRef(false);
  const repeatCallBackRef = useRef(() => setCurrentStep(3));

  // 步骤2：分段策略完成，接收配置并跳转步骤2（原文对比）
  const handleStep2Next = (step, config) => {
    if (config) {
      setSegmentRules(config);
    }
    setCurrentStep(2);
  };

  // 步骤2：原文对比回调，控制下一步按钮禁用状态
  const handlePreviewResult = (isSuccess) => {
    setIsNextDisabled(!isSuccess);
  };

  // 下一步：按当前步骤跳转
  const handleNext = () => {
    switch (currentStep) {
      case 1: // 步骤1→步骤2（分段→对比）
        if (fileUploadStep2Ref.current) {
          fileUploadStep2Ref.current.handleNext();
        }
        break;
      case 2: // 步骤2→步骤3（对比→处理）
        // 修复：先保存配置，成功后再跳转步骤3（移除提前setCurrentStep）
        if (segmentRules) {
          handleSave(segmentRules);
        }
        break;
      default:
        break;
    }
  };

  // 上一步：按当前步骤回退
  const handleBack = () => {
    switch (currentStep) {
      case 1:
        navigate(-1);
        break;
      case 2:
        setCurrentStep(1);
        break;
      case 3:
        setCurrentStep(2);
        break;
      default:
        break;
    }
  };

  // API：保存分段策略配置（核心修复点）
  const handleSave = (_config) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);

    const apiConfig = {
      knowledge_id: Number(_config.rules.knowledgeId || initFileData.knowledgeId || knowledgeId),
      separator: _config.rules.separator,
      separator_rule: _config.rules.separatorRule,
      chunk_size: _config.rules.chunkSize,
      chunk_overlap: _config.rules.chunkOverlap,
      excel_rule: _config.cellGeneralConfig,
      kb_file_id: _config.rules.fileList[0].id,
      retain_images: _config.rules.retainImages,
      enable_formula: _config.rules.enableFormula,
      force_ocr: _config.rules.forceOcr,
      fileter_page_header_footer: _config.rules.pageHeaderFooter
    };

    captureAndAlertRequestErrorHoc(
      rebUploadFile(apiConfig)
        .then(res => {
          // 1. 修复重复文件判断（单个对象处理）
          const _repeatFiles = res.status === 3 ? [res] : [];
          if (_repeatFiles.length) {
            setRepeatFiles(_repeatFiles);
            return; // 有重复文件时不跳转步骤
          }

          // 2. 修复文件ID更新（直接使用res.id，无需数组索引）
          setResultFiles(prevFiles => 
            prevFiles.map(file => ({
              ...file,
              fileId: res.id // 关键修复：单个对象直接取id
            }))
          );
          console.log(resultFiles,56);
          
          // 3. 修复步骤跳转时机（确保数据更新后再跳转）
          message({ variant: 'success', description: t('调整分段策略成功') });
          setCurrentStep(3); // 只有成功且无重复时才跳转
        })
        .finally(() => {
          submittingRef.current = false;
          setIsSubmitting(false);
        })
    );

    _tempConfigRef.current = apiConfig;
  };

  const handleRetry = (objs) => {
    setRetryLoad(true);
    const params = {
      knowledge_id: Number(_tempConfigRef.current.knowledge_id),
      separator: _tempConfigRef.current.separator,
      separator_rule: _tempConfigRef.current.separator_rule,
      chunk_size: _tempConfigRef.current.chunk_size,
      chunk_overlap: _tempConfigRef.current.chunk_overlap,
      file_objs: objs
    };

    captureAndAlertRequestErrorHoc(
      retryKnowledgeFileApi(params)
        .then(res => {
          // 补充：更新覆盖后的文件ID
          setResultFiles(prevFiles => 
            prevFiles.map(file => ({
              ...file,
              fileId: res.id // 假设retry接口也返回单个对象带id
            }))
          );
          setRepeatFiles([]);
          setRetryLoad(false);
          message({ variant: 'success', description: t('解析成功') });
          repeatCallBackRef.current();
        })
        .catch(() => {
          setRetryLoad(false); // 错误时也需停止加载
        })
    );
  };

  return (
    <div className="relative h-full flex flex-col">
      {/* 顶部返回栏 */}
      <div className="pt-4 px-4">
        <div className="flex items-center mb-4">
          <Button
            variant="outline"
            size="icon"
            className="bg-[#fff] size-8"
            onClick={handleBack}
          >
            <ChevronLeft />
          </Button>
          <span className="text-foreground text-sm font-black pl-4">返回知识库详情</span>
        </div>

        {/* 调整模式步骤条 */}
        <StepProgress
          align="center"
          currentStep={currentStep}
          labels={AdjustStepLabels.map(label => t(label))}
        />
      </div>

      {/* 步骤内容区域 */}
      <div className="flex flex-1 overflow-hidden px-4">
        <div className="w-full overflow-y-auto">
          <div className="h-full py-4">
            {console.log(resultFiles,33)}
            {currentStep === 1 && (
              <FileUploadStep2
                ref={fileUploadStep2Ref}
                step={currentStep}
                resultFiles={resultFiles}
                isSubmitting={isSubmitting}
                onNext={handleStep2Next}
                onPrev={handleBack}
                kId={knowledgeId}
                isAdjustMode
              />
            )}

            {/* 步骤2：原文对比 */}
            {currentStep === 2 && segmentRules && (
              <>
                <PreviewResult
                  rules={segmentRules.rules}
                  resultFiles={resultFiles}
                  onPrev={handleBack}
                  onNext={() => handleSave(segmentRules)} // 直接调用保存，移除提前跳转
                  handlePreviewResult={handlePreviewResult}
                  step={currentStep}
                  previewCount={0}
                  applyEachCell={segmentRules.applyEachCell}
                  cellGeneralConfig={segmentRules.cellGeneralConfig}
                  kId={knowledgeId}
                  isAdjustMode
                />
{console.log(isNextDisabled,666)}
                {/* 步骤2底部按钮 */}
                <div className="fixed bottom-2 right-12 flex gap-4 bg-white p-2 rounded-lg shadow-sm z-10">
                  <Button
                    className="h-8"
                    variant="outline"
                    onClick={handleBack}
                  >
                    {t('previousStep')}
                  </Button>
                  <Button
                    className="h-8"
                    onClick={handleNext}
                    disabled={isNextDisabled || isSubmitting}
                  >
                    {isSubmitting ? <LoadingIcon className="h-4 w-4 mr-1" /> : null}
                    {t('nextStep')}
                  </Button>
                </div>
              </>
            )}

            {/* 步骤3：数据处理 */}
            {currentStep === 3 && (
              <FileUploadStep4 data={resultFiles} kId={knowledgeId} isAdjustMode />
            )}
          </div>
        </div>
      </div>

      {/* 重复文件提醒弹窗 */}
      <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('modalTitle')}</DialogTitle>
            <DialogDescription>{t('adjustModalMessage')}</DialogDescription>
          </DialogHeader>
          <ul className="overflow-y-auto max-h-[400px] py-2">
            {repeatFiles.map(el => (
              <li key={el.id} className="py-1 text-red-500 text-sm">{el.remark}</li>
            ))}
          </ul>
          <DialogFooter>
            <Button className="h-8" variant="outline" onClick={() => {
              setRepeatFiles([]);
              repeatCallBackRef.current();
            }}>
              {t('keepOriginal')}
            </Button>
            <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
              {retryLoad && <span className="loading loading-spinner loading-xs mr-1"></span>}
              {t('override')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
