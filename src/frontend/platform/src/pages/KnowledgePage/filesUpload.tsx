import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";
import PreviewResult from "./components/PreviewResult";
import { LoadingIcon } from "@/components/bs-icons/loading";

// 正常模式固定步骤标签（4步）
const NormalStepLabels = [
  '上传文件',
  '分段策略',
  '原文对比',
  '数据处理'
];

export default function FilesUpload() {
  const { t } = useTranslation('knowledge');
  const navigate = useNavigate();
  const location = useLocation();
  const { id: knowledgeId } = useParams(); // 从路由获取知识库ID
  const { message } = useToast();

  // 正常模式专属状态（无调整模式相关判断）
  const [currentStep, setCurrentStep] = useState(1); // 初始步骤：1（上传文件）
  const [resultFiles, setResultFiles] = useState([]); // 上传的文件列表
  const [segmentRules, setSegmentRules] = useState(null); // 分段策略配置
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isNextDisabled, setIsNextDisabled] = useState(false);
  const [repeatFiles, setRepeatFiles] = useState([]); // 重复文件提醒
  const [retryLoad, setRetryLoad] = useState(false);

  // Ref管理
  const fileUploadStep2Ref = useRef(null); // Step2（分段策略）组件引用
  const _tempConfigRef = useRef({}); // 临时存储API配置
  const submittingRef = useRef(false); // 防止重复提交
  const repeatCallBackRef = useRef(() => setCurrentStep(4)); // 重复文件处理后跳转步骤（4：数据处理）

  // 步骤1：文件上传完成，跳转步骤2
  const handleStep1Next = (files) => {
    setResultFiles(files);
    setCurrentStep(2);
  };

  // 步骤2：分段策略完成，接收配置并跳转步骤3
  const handleStep2Next = (step, config) => {
    if (config) {
      setSegmentRules(config);
    }
    setCurrentStep(3); // 固定跳步骤3（原文对比）
  };

  // 步骤3：原文对比回调，控制下一步按钮禁用状态
  const handlePreviewResult = (isSuccess) => {
    if (currentStep === 3) {
      console.log("更新按钮状态：", { isSuccess, currentStep });
      setIsNextDisabled(!isSuccess);
    }
  };

  // 下一步：按当前步骤跳转
  const handleNext = () => {
    switch (currentStep) {
      case 2: // 步骤2→步骤3（分段→对比）
        if (fileUploadStep2Ref.current) {
          fileUploadStep2Ref.current.handleNext();
        }
        break;
      case 3: // 步骤3→步骤4（对比→处理）
        setCurrentStep(4);
        if (segmentRules) {
          handleSave(segmentRules); // 保存配置
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
        navigate(-1); // 步骤1回退：返回知识库列表
        break;
      case 2:
        setCurrentStep(1); // 步骤2→步骤1
        break;
      case 3:
        setCurrentStep(2); // 步骤3→步骤2
        break;
      case 4:
        setCurrentStep(3); // 步骤4→步骤3
        break;
      default:
        break;
    }
  };

  // API：保存分段策略配置（正常模式专属）
  const handleSave = (_config) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);

    /**
     * 将 UI 可见的换行转义("\\n")还原为真实换行("\n")
     */
    const normalizeSeparators = (arr) =>
      (arr || []).map((s) =>
        typeof s === 'string' ? s.replace(/\\n/g, '\n') : s
      );

    // 正常模式API参数格式
    const apiConfig = {
      knowledge_id: Number(_config.rules.knowledgeId || knowledgeId),
      separator: normalizeSeparators(_config.rules.separator),
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
        message({ variant: 'success', description: t('addSuccess') });
        setCurrentStep(4);
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

  // API：步骤1直接用默认配置保存（正常模式专属）
  const handleSaveByDefaultConfig = async (_config) => {
    await captureAndAlertRequestErrorHoc(subUploadLibFile(_config).then(res => {
      const _repeatFiles = res.filter(e => e.status === 3);
      if (_repeatFiles.length) {
        setRepeatFiles(_repeatFiles);
        repeatCallBackRef.current = () => navigate(-1);
      } else {
        message({ variant: 'success', description: "添加成功" });
        navigate(-1);
      }
    }));
  };

  // API：重试重复文件（覆盖上传）
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
      message({ variant: 'success', description: t('addSuccess') });
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
            onClick={() => navigate(-1)}
          >
            <ChevronLeft />
          </Button>
          <span className="text-foreground text-sm font-black pl-4">返回知识库</span>
        </div>

        {/* 正常模式步骤条（4步） */}
        <StepProgress
          align="center"
          currentStep={currentStep}
          labels={NormalStepLabels.map(label => t(label))}
        />
      </div>

      {/* 步骤内容区域（正常模式专属步骤） */}
      <div className="flex flex-1 overflow-hidden px-4">
        <div className="w-full overflow-y-auto">
          <div className="h-full">
            {/* 步骤1：文件上传（正常模式独有） */}
            {currentStep === 1 && (
              <FileUploadStep1
                onNext={handleStep1Next}
                onSave={handleSaveByDefaultConfig}
                kId={knowledgeId} // 传递知识库ID
                initialFiles={resultFiles}
              />
            )}
            {/* 步骤2：分段策略 */}
            {currentStep === 2 && ( // 步骤2或3时，第二步始终挂载（仅控制显示）
              <div className={currentStep === 2 ? "block" : "hidden"}>
                <FileUploadStep2
                  ref={fileUploadStep2Ref}
                  step={currentStep}
                  resultFiles={resultFiles}
                  isSubmitting={isSubmitting}
                  onNext={handleStep2Next}
                  onPrev={handleBack}
                  kId={knowledgeId}
                />
              </div>
            )}


            {/* 步骤3：原文对比 */}
            {currentStep === 3 && segmentRules && (
              <div className="block"> {/* 第三步显示时，第二步被隐藏但不卸载 */}
                <PreviewResult
                  rules={segmentRules.rules}
                  resultFiles={resultFiles}
                  handlePreviewResult={handlePreviewResult}
                  onPrev={handleBack}
                  onNext={() => {
                    setCurrentStep(4);
                    handleSave(segmentRules);
                  }}
                  onDeleteFile={(filePath) => {
                    setSegmentRules(prev => (
                      {
                        ...prev,
                        rules: {
                          ...prev.rules,
                          fileList: prev.rules.fileList.filter(file => file.filePath !== filePath)
                        }
                      }
                    ))
                    setResultFiles(prev => (
                      prev.filter(file => file.file_path !== filePath)
                    ))
                  }}
                  step={currentStep}
                  previewCount={0}
                  applyEachCell={segmentRules.applyEachCell}
                  cellGeneralConfig={segmentRules.cellGeneralConfig}
                  kId={knowledgeId}
                  showPreview={true}
                />

                {/* 步骤3底部按钮 */}
                <div className="fixed bottom-2 right-12 flex gap-4 bg-white p-2 rounded-lg shadow-sm z-10">
                  <Button variant="outline" onClick={handleBack}>
                    {t('previousStep')}
                  </Button>
                  <Button onClick={handleNext} disabled={isNextDisabled || isSubmitting || resultFiles.length === 0}>
                    {isSubmitting ? <LoadingIcon className="h-4 w-4 mr-1" /> : null}
                    {t('nextStep')}
                  </Button>
                </div>
              </div>
            )}


            {/* 步骤4：数据处理 */}
            {currentStep === 4 && (
              <FileUploadStep4 data={resultFiles} />
            )}
          </div>
        </div>
      </div>

      {/* 重复文件提醒弹窗（正常模式共用） */}
      <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('modalTitle')}</DialogTitle>
            <DialogDescription>{t('modalMessage')}</DialogDescription>
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