import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
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
 console.log(knowledgeId,21);
 
  // 从路由状态获取调整模式的初始数据（必须传文件数据）
  const initFileData = location.state?.fileData;
  if (!initFileData) {
    navigate(-1); // 无数据时回退
    return null;
  }

  // 调整模式专属状态（无正常模式判断）
  const [currentStep, setCurrentStep] = useState(1); // 初始步骤：1（分段策略）
  const [resultFiles, setResultFiles] = useState([
    // 固定从路由状态生成文件列表（跳过上传）
    {
      id: initFileData.id,
      fileName: initFileData.name,
      file_path: initFileData.filePath,
      suffix: initFileData.suffix,
      fileType: initFileData.fileType === 'table' ? 'table' : 'file'
    }
  ]);
  const [segmentRules, setSegmentRules] = useState(null); // 分段策略配置
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isNextDisabled, setIsNextDisabled] = useState(true);
  const [repeatFiles, setRepeatFiles] = useState([]); // 重复文件提醒
  const [retryLoad, setRetryLoad] = useState(false);

  // Ref管理
  const fileUploadStep2Ref = useRef(null); // Step2（分段策略）组件引用
  const _tempConfigRef = useRef({}); // 临时存储API配置
  const submittingRef = useRef(false); // 防止重复提交
  const repeatCallBackRef = useRef(() => setCurrentStep(3)); // 重复文件处理后跳转步骤（3：数据处理）

  // 步骤2：分段策略完成，接收配置并跳转步骤3
  const handleStep2Next = (step, config) => {
    if (config) {
      setSegmentRules(config);
    }
    setCurrentStep(2); // 固定跳步骤2（原文对比）
  };

  // 步骤2：原文对比回调，控制下一步按钮禁用状态
  const handlePreviewResult = (isSuccess) => {
    setIsNextDisabled(!isSuccess);
  };

  // 下一步：按当前步骤跳转（调整模式3步逻辑）
  const handleNext = () => {
    switch (currentStep) {
      case 1: // 步骤1→步骤2（分段→对比）
        if (fileUploadStep2Ref.current) {
          fileUploadStep2Ref.current.handleNext();
        }
        break;
      case 2: // 步骤2→步骤3（对比→处理）
        setCurrentStep(3);
        if (segmentRules) {
          handleSave(segmentRules); // 保存配置
        }
        break;
      default:
        break;
    }
  };

  // 上一步：按当前步骤回退（调整模式3步逻辑）
  const handleBack = () => {
    switch (currentStep) {
      case 1:
        navigate(-1); // 步骤1回退：返回知识库详情
        break;
      case 2:
        setCurrentStep(1); // 步骤2→步骤1
        break;
      case 3:
        setCurrentStep(2); // 步骤3→步骤2
        break;
      default:
        break;
    }
  };

  // API：保存分段策略配置（调整模式专属）
  const handleSave = (_config) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);
console.log(resultFiles.id,_config.rules.knowledgeId , initFileData.knowledgeId,2222);

    // 调整模式API参数格式（复用文件数据）
    const apiConfig = {
      knowledge_id: Number(_config.rules.knowledgeId || initFileData.knowledgeId), // 从文件数据取知识库ID
      separator: _config.rules.separator,
      separator_rule: _config.rules.separatorRule,
      chunk_size: _config.rules.chunkSize,
      chunk_overlap: _config.rules.chunkOverlap,
      file_list: _config.rules.fileList.map(item => ({
        file_path: item.filePath,
        excel_rule: _config.applyEachCell ? item.excelRule : _config.cellGeneralConfig
      })),
      retain_images: _config.rules.retainImages,
      enable_formula: _config.rules.enableFormula,
      force_ocr: _config.rules.forceOcr,
      fileter_page_header_footer: _config.rules.pageHeaderFooter
    };

    captureAndAlertRequestErrorHoc(subUploadLibFile(apiConfig).then(res => {
      const _repeatFiles = res.filter(e => e.status === 3);
      if (_repeatFiles.length) {
        setRepeatFiles(_repeatFiles);
      } else {
        message({ variant: 'success', description: t('adjustSuccess') }); // 调整成功文案
        setCurrentStep(3);
      }

      // 更新文件ID
      setResultFiles(files => files.map((file, index) => ({
        ...file,
        fileId: res[index]?.id
      })));
    }).finally(() => {
      submittingRef.current = false;
      setIsSubmitting(false);
    }));

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

    captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(params).then(res => {
      setRepeatFiles([]);
      setRetryLoad(false);
      message({ variant: 'success', description: t('adjustSuccess') });
      repeatCallBackRef.current();
    }));
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

        {/* 调整模式步骤条（3步） */}
        <StepProgress
          align="center"
          currentStep={currentStep}
          labels={AdjustStepLabels.map(label => t(label))}
        />
      </div>

      {/* 步骤内容区域（调整模式专属步骤） */}
      <div className="flex flex-1 overflow-hidden px-4">
        <div className="w-full overflow-y-auto">
          <div className="h-full py-4">
            {currentStep === 1 && (
              <FileUploadStep2
                ref={fileUploadStep2Ref}
                step={currentStep}
                resultFiles={resultFiles}
                isSubmitting={isSubmitting}
                onNext={handleStep2Next}
                onPrev={handleBack}
                kId={knowledgeId} // 从文件数据传知识库ID
                isAdjustMode // 给子组件标记调整模式（可选，子组件如需差异化处理）
              />
            )}

            {/* 步骤2：原文对比 */}
            {currentStep === 2 && segmentRules && (
              <>
                <PreviewResult
                  rules={segmentRules.rules}
                  resultFiles={resultFiles}
                  onPrev={handleBack}
                  onNext={() => {
                    setCurrentStep(3);
                    handleSave(segmentRules);
                  }}
                  onPreviewResult={handlePreviewResult}
                  step={currentStep}
                  previewCount={0}
                  applyEachCell={segmentRules.applyEachCell}
                  cellGeneralConfig={segmentRules.cellGeneralConfig}
                   kId={knowledgeId} 
                  isAdjustMode // 子组件差异化标记
                />

                {/* 步骤2底部按钮（固定） */}
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
              <FileUploadStep4 data={resultFiles} isAdjustMode />
            )}
          </div>
        </div>
      </div>

      {/* 重复文件提醒弹窗（调整模式共用） */}
      <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('modalTitle')}</DialogTitle>
            <DialogDescription>{t('adjustModalMessage')}</DialogDescription> {/* 调整模式专属提示文案 */}
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