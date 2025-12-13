import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { rebUploadFile, retryKnowledgeFileApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import DialogWithRepeatFiles from "./components/DuplicateFileDialog";
import FileUploadStep2 from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";
import PreviewResult from "./components/PreviewResult";

// Adjustment mode fixed step labels (3 steps)
const getAdjustStepLabels = (t) => [
  t('segmentStrategy'),
  t('textComparison'),
  t('dataProcessing')
];

export default function AdjustFilesUpload() {
  const { t } = useTranslation('knowledge');
  const navigate = useNavigate();
  const location = useLocation();
  const { message } = useToast();
  const { fileId: knowledgeId } = useParams();

  // Get initial data for adjustment mode from route state (must pass file data)
  const initFileData = location.state?.fileData;
  useEffect(() => {
    // If no initialization data, it means direct access, redirect to /filelib
    if (!initFileData) {
      navigate('/filelib', { replace: true });
    }
  }, [initFileData, navigate]);
  if (!initFileData) {
    navigate(-1); // Roll back when no data
    return null;
  }
  // Adjustment mode exclusive state
  const [currentStep, setCurrentStep] = useState(1);
  const getParsedSplitRule = (rawSplitRule) => {
    // Handle no split_rule or empty case
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
      // Parse JSON string
      const parsed = JSON.parse(rawSplitRule);
      // Format adaptation: Unify field format to avoid child component processing
      return {
        knowledge_id: parsed.knowledge_id || "", // Knowledge base ID
        // Separator: Ensure it's an array, default double newline + single newline
        separator: Array.isArray(parsed.separator) ? parsed.separator : ["\\n\\n", "\\n"],
        // Separator rule: Ensure consistent length with separator, default after
        separator_rule: Array.isArray(parsed.separator_rule)
          ? parsed.separator_rule
          : ["after", "after"],
        // Chunk size: Convert number to string (child component uses string format), default 1000
        chunk_size: parsed.chunk_size ?? 1000,
        // Overlap size: Default 100
        chunk_overlap: parsed.chunk_overlap ?? 100,
        // Boolean conversion: 0→false, 1→true, default false
        retain_images: parsed.retain_images === 1,
        force_ocr: parsed.force_ocr === 1,
        enable_formula: parsed.enable_formula === 1,
        filter_page_header_footer: parsed.filter_page_header_footer === 1,
        // Table rules: Default value fallback
        excel_rule: {
          slice_length: parsed.excel_rule?.slice_length || 10,
          append_header: parsed.excel_rule?.append_header === 1,
          header_start_row: parsed.excel_rule?.header_start_row || 1,
          header_end_row: parsed.excel_rule?.header_end_row || 1
        }
      };
    } catch (error) {
      // Return default config when parsing fails to avoid crash
      console.error("split_rule parse failed:", error);
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
      fileName: initFileData.name || initFileData.file_name, // Compatible field name
      file_path: initFileData.filePath || initFileData.object_name, // Compatible file path
      suffix: initFileData.suffix || initFileData.file_name?.split(".").pop() || "", // Parse suffix
      previewUrl: initFileData.previewUrl,
      fileType: fileType,
      split_rule: getParsedSplitRule(initFileData.split_rule), // Pass converted config object
      isEtl4lm: initFileData.fileType,
    }
  ]);

  const [segmentRules, setSegmentRules] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isNextDisabled, setIsNextDisabled] = useState(false);
  const [repeatFiles, setRepeatFiles] = useState([]);
  const [retryLoad, setRetryLoad] = useState(false);

  // Ref management
  const fileUploadStep2Ref = useRef(null);
  const _tempConfigRef = useRef({});
  const submittingRef = useRef(false);
  const repeatCallBackRef = useRef(() => setCurrentStep(3));

  // Step 2: Segmentation strategy completed, receive config and jump to step 2 (original text comparison)
  const handleStep2Next = (step, config) => {
    if (config) {
      setSegmentRules(config);
    }
    setCurrentStep(2);
  };

  // Step 2: Original text comparison callback, control next button disabled state
  const handlePreviewResult = (isSuccess) => {
    setIsNextDisabled(!isSuccess);
  };

  // Next: Jump based on current step
  const handleNext = () => {
    switch (currentStep) {
      case 1: // Step 1 → Step 2 (segment → compare)
        if (fileUploadStep2Ref.current) {
          fileUploadStep2Ref.current.handleNext();
        }
        break;
      case 2: // Step 2 → Step 3 (compare → process)
        // Fix: Save config first, then jump to step 3 after success (removed premature setCurrentStep)
        if (segmentRules) {
          handleSave(segmentRules);
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

  // API: Save segmentation strategy config (core fix point)
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

    const apiConfig = {
      knowledge_id: Number(_config.rules.knowledgeId || initFileData.knowledgeId || knowledgeId),
      separator: normalizeSeparators(_config.rules.separator),
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

          // 1. Fix duplicate file check (single object processing)
          const _repeatFiles = res.status === 3 ? [res] : [];
          if (_repeatFiles.length) {
            setRepeatFiles(_repeatFiles);
            return; // Don't jump steps when there are duplicate files
          }

          // 2. Fix file ID update (directly use res.id, no need for array index)
          setResultFiles(prevFiles =>
            prevFiles.map(file => ({
              ...file,
              fileId: res.id // Key fix: Single object directly get id
            }))
          );

          // 3. Fix step jump timing (ensure data is updated before jumping)
          message({ variant: 'success', description: t('adjustSegmentStrategySuccess') });
          setCurrentStep(3); // Only jump when successful and no duplicates
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
          // Additional: Update file ID after overwrite
          setResultFiles(prevFiles =>
            prevFiles.map(file => ({
              ...file,
              fileId: res.id // Assume retry API also returns single object with id
            }))
          );
          setRepeatFiles([]);
          setRetryLoad(false);
          message({ variant: 'success', description: t('parseSuccess') });
          repeatCallBackRef.current();
        })
        .catch(() => {
          setRetryLoad(false); // Also need to stop loading on error
        })
    );
  };

  const handleUnRetry = () => {
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
          <span className="text-foreground text-sm font-black pl-4">{t('backToKnowledgeDetail')}</span>
        </div>

        {/* Adjustment mode step progress */}
        <StepProgress
          align="center"
          currentStep={currentStep}
          labels={getAdjustStepLabels(t)}
        />
      </div>

      {/* Step content area */}
      <div className="flex flex-1 px-4">
        <div className="w-full">
          <div className="h-full py-4">
            <div className={currentStep === 1 ? "block" : "hidden"}>
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
            </div>
            {/* Step 2: Original text comparison */}
            {currentStep === 2 && segmentRules && (
              <div className="block">
                <PreviewResult
                  rules={segmentRules.rules}
                  resultFiles={resultFiles}
                  onPrev={handleBack}
                  onNext={() => handleSave(segmentRules)}
                  handlePreviewResult={handlePreviewResult}
                  step={currentStep}
                  previewCount={0}
                  applyEachCell={segmentRules.applyEachCell}
                  cellGeneralConfig={segmentRules.cellGeneralConfig}
                  kId={knowledgeId}
                  isAdjustMode
                />

                {/* Step 2 bottom buttons */}
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
              </div>
            )}
            {/* Step 3: Data processing */}
            {currentStep === 3 && (
              <FileUploadStep4 data={resultFiles} kId={knowledgeId} isAdjustMode />
            )}
          </div>
        </div>
      </div>

      {/* Duplicate file reminder dialog */}
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
