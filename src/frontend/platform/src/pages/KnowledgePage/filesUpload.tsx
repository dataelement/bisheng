import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import DialogWithRepeatFiles from "./components/DuplicateFileDialog";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2, { Step2PersistState } from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";
import PreviewResult from "./components/PreviewResult";

// Normal mode fixed step labels (4 steps)
const getNormalStepLabels = (t) => [
  t('uploadFile'),
  t('segmentStrategy'),
  t('textComparison'),
  t('dataProcessing')
];

export default function FilesUpload() {
  const { t } = useTranslation('knowledge');
  const navigate = useNavigate();
  const location = useLocation();
  const { id: knowledgeId } = useParams(); // Get knowledge base ID from route
  const { message } = useToast();

  // Normal mode exclusive states (no adjustment mode related logic)
  const [currentStep, setCurrentStep] = useState(1); // Initial step: 1 (upload file)
  const [resultFiles, setResultFiles] = useState([]); // Uploaded file list
  const [segmentRules, setSegmentRules] = useState(null); // Segmentation strategy config
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isNextDisabled, setIsNextDisabled] = useState(false);
  const [repeatFiles, setRepeatFiles] = useState([]); // Duplicate file reminder
  const [retryLoad, setRetryLoad] = useState(false);

  // Key addition: Manage Step2's persistent state
  const [step2PersistState, setStep2PersistState] = useState<Step2PersistState | undefined>();

  // Ref management
  const fileUploadStep2Ref = useRef(null); // Step2 (segmentation strategy) component reference
  const _tempConfigRef = useRef({}); // Temporary storage of API config
  const submittingRef = useRef(false); // Prevent duplicate submission
  const repeatCallBackRef = useRef(() => setCurrentStep(4)); // Jump to step after duplicate file handling (4: data processing)

  // Key addition: Receive Step2's state update, save to parent component
  const handleStep2StateChange = (state: Step2PersistState) => {
    setStep2PersistState(state);
  };

  // Step 1: File upload completed, jump to step 2
  const handleStep1Next = async (files) => {
    setResultFiles(files);

    const _repeatFiles = files.filter(e => e.repeat);
    if (_repeatFiles.length) {
      setRepeatFiles(_repeatFiles.map(file => ({
        ...file,
        file_name: file.fileName,
        remark: `${file.fileName} 对应已存在文件 ${file.fileName}`
      })));
    } else {
      setCurrentStep(2);
    }
  };

  // Step 2: Segmentation strategy completed, receive config and jump to step 3
  const handleStep2Next = (step, config) => {
    if (config) {
      setSegmentRules(config);
    }
    setCurrentStep(3); // Fixed jump to step 3 (original text comparison)
  };

  // Step 3: Original text comparison callback, control next button disabled state
  const handlePreviewResult = (isSuccess) => {
    if (currentStep === 3) {
      setIsNextDisabled(!isSuccess);
    }
  };

  // Next: Jump based on current step
  const handleNext = () => {
    switch (currentStep) {
      case 2: // Step 2 → Step 3 (segment → compare)
        if (fileUploadStep2Ref.current) {
          fileUploadStep2Ref.current.handleNext();
        }
        break;
      case 3: // Step 3 → Step 4 (compare → process)
        setCurrentStep(4);
        if (segmentRules) {
          handleSave(segmentRules); // Save config
        }
        break;
      default:
        break;
    }
  };

  // Previous: Rollback based on current step
  const handleBack = () => {
    switch (currentStep) {
      case 1:
        navigate(-1); // Step 1 rollback: return to knowledge base list
        break;
      case 2:
        setCurrentStep(1); // Step 2 → Step 1
        break;
      case 3:
        setCurrentStep(2); // Step 3 → Step 2
        break;
      case 4:
        setCurrentStep(3); // Step 4 → Step 3
        break;
      default:
        break;
    }
  };

  // API: Save segmentation strategy config (normal mode exclusive)
  const handleSave = (_config) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setIsSubmitting(true);

    /**
     * Convert UI-visible newline escape sequences ("\\n") back to real newlines ("\n")
     */
    const normalizeSeparators = (arr) =>
      (arr || []).map((s) =>
        typeof s === 'string' ? s.replace(/\\n/g, '\n') : s
      );

    // Normal mode API parameter format
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
      const repeatFilesRes = res.filter(e => e.status === 3);
      if (repeatFilesRes.length) {
        const newRepeatFiles = repeatFilesRes.filter(file =>
          // Same timestamp, no overwrite
          !resultFiles.some(item => item.fileName === file.file_name && item.time && item.time === file.update_time))
        setRepeatFiles(newRepeatFiles);
        if (!newRepeatFiles.length) {
          handleRetry(repeatFilesRes)
        }
      } else {
        message({ variant: 'success', description: t('addSuccess') });
        setCurrentStep(4);
      }

      // Update file ID
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

  // API: Save directly with default config in step 1 (normal mode exclusive)
  const handleSaveByDefaultConfig = async (_config) => {
    await captureAndAlertRequestErrorHoc(subUploadLibFile(_config).then(res => {
      const _repeatFiles = res.filter(e => e.status === 3);
      if (_repeatFiles.length) {
        setRepeatFiles(_repeatFiles);
        repeatCallBackRef.current = () => navigate(-1);
      } else {
        message({ variant: 'success', description: t('addSuccess') });
        navigate(-1);
      }
    }));
  };

  // API: Retry duplicate files (overwrite upload)
  const handleRetry = (objs) => {
    if (currentStep === 1 && !repeatCallBackRef.current) {
      setRepeatFiles([]);
      return setCurrentStep(2);
    }
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
    }), () => {
      setRetryLoad(false);
    });
  };

  const handleUnRetry = () => {
    if (currentStep === 1) {
      const files = resultFiles.filter((item) => {
        return repeatFiles.every((repeatItem) => {
          return repeatItem.file_path !== item.file_path;
        });
      })
      setResultFiles(files)
      if (files.length === 0) {
        return navigate(-1);
      }
      setRepeatFiles([]);
      return setCurrentStep(2);
    }
    setRepeatFiles([]);
    repeatCallBackRef.current();
  }
  return (
    <div className="relative h-full flex flex-col">
      {/* Top return bar */}
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
          <span className="text-foreground text-sm font-black pl-4">{t('backToKnowledge')}</span>
        </div>

        {/* Normal mode step progress (4 steps) */}
        <StepProgress
          align="center"
          currentStep={currentStep}
          labels={getNormalStepLabels(t)}
        />
      </div>

      {/* Step content area (normal mode exclusive steps) */}
      <div className="flex flex-1 overflow-hidden px-4">
        <div className="w-full overflow-y-auto">
          <div className="h-full">
            {/* Step 1: File upload (normal mode exclusive) */}
            {currentStep === 1 && (
              <FileUploadStep1
                onNext={handleStep1Next}
                onSave={handleSaveByDefaultConfig}
                kId={knowledgeId} // Pass knowledge base ID
                initialFiles={resultFiles}
              />
            )}
            {/* Step 2: Segmentation strategy - only added 2 props */}
            {currentStep === 2 && (
              <div className={currentStep === 2 ? "block" : "hidden"}>
                <FileUploadStep2
                  ref={fileUploadStep2Ref}
                  step={currentStep}
                  resultFiles={resultFiles}
                  isSubmitting={isSubmitting}
                  onNext={handleStep2Next}
                  onPrev={handleBack}
                  kId={knowledgeId}
                  persistState={step2PersistState} // Added: Pass saved state
                  onPersistStateChange={setStep2PersistState} // Added: Pass state update callback
                />
              </div>
            )}


            {/* Step 3: Original text comparison */}
            {currentStep === 3 && segmentRules && (
              <div className="block"> {/* When step 3 is displayed, step 2 is hidden but not unmounted */}
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

                {/* Step 3 bottom buttons */}
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


            {/* Step 4: Data processing */}
            {currentStep === 4 && (
              <FileUploadStep4 data={resultFiles} />
            )}
          </div>
        </div>
      </div>

      {/* Duplicate file reminder dialog (shared for normal mode) */}
      <DialogWithRepeatFiles
        repeatFiles={repeatFiles}
        setRepeatFiles={setRepeatFiles}
        unRetry={handleUnRetry}
        onRetry={handleRetry}
        retryLoad={retryLoad}
        t={t}
      />
    </div>
  );
}