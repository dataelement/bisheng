import { Button, toast } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import DropZone from "@/components/bs-comp/knowledgeUploadComponent/DropZone";
import StepProgress from "@/components/bs-ui/step";
import { knowledgeUploadsApi } from "@/controllers/API/knowledgeUploads";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import FileUploadStep2, { type Step2PersistState } from "./FileUploadStep2";
import { SpaceUploadPreview, type PreviewBook } from "./SpaceUploadPreview";
import { SpaceUploadProgress } from "./SpaceUploadProgress";
import {
  initialWizardStrategy,
  wizardOverrides,
  type WizardFile,
  type WizardStrategy,
} from "./uploadWizardRules";
import { useSpaceUploadQueue } from "./useSpaceUploadQueue";

export type { Upload } from "./useSpaceUploadQueue";
interface SpaceFileUploadPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  onBack?: () => void;
}
export function SpaceFileUploadPanel(props: SpaceFileUploadPanelProps) {
  return (
    <UploadWizard
      key={JSON.stringify([props.scope, props.spaceId, props.parentId])}
      {...props}
    />
  );
}
function UploadWizard({
  scope,
  spaceId,
  parentId,
  onBack,
}: SpaceFileUploadPanelProps) {
  const { t } = useTranslation("knowledge");
  const instance = useId();
  const queue = useSpaceUploadQueue({ scope, spaceId, parentId });
  const [step, setStep] = useState(1);
  const [strategy, setStrategy] = useState<WizardStrategy>();
  const [book, setBook] = useState<PreviewBook>({});
  const [busy, setBusy] = useState(false);
  const previewBusy = useRef(false);
  const handleBusy = useCallback((value: boolean) => {
    previewBusy.current = value;
    setBusy(value);
  }, []);
  const folderInput = useRef<HTMLInputElement>(null);
  const settings = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "upload-settings",
      instance,
      parentId,
    ],
    queryFn: ({ signal }) =>
      knowledgeUploadsApi.getUploadSettings(spaceId, parentId, signal),
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    onError: showApiError,
  });
  const files = useMemo<WizardFile[]>(
    () =>
      queue.files.map(({ file, staged }) => {
        const suffix = file.name.split(".").pop()?.toLowerCase() ?? "";
        return {
          id: staged.upload_id!,
          fileName: file.name,
          file_path: staged.file_path,
          suffix,
          fileType: ["xls", "xlsx", "csv", "et"].includes(suffix)
            ? "table"
            : "file",
          split_rule: {},
        };
      }),
    [queue.files],
  );
  const ready = Boolean(
    settings.data &&
    queue.jobs.length &&
    queue.jobs.every((job) => job.phase === "staged"),
  );
  const handlePreview = useCallback(
    (id: string, record: PreviewBook[string]) => {
      setBook((previous) =>
        previous[id]?.value === record.value &&
        previous[id]?.fingerprint === record.fingerprint
          ? previous
          : { ...previous, [id]: record },
      );
    },
    [],
  );
  const handleStrategy = useCallback(
    (value: Step2PersistState) => setStrategy(value as WizardStrategy),
    [],
  );
  const invalidRules = () =>
    toast.show({ type: "warning", message: t("f118.invalid_defaults") });
  const handleNext = () => {
    if (!ready || !settings.data) return;
    setStrategy((previous) => {
      if (!previous)
        return initialWizardStrategy(
          settings.data.effective_defaults,
          spaceId,
          files,
        );
      const seeded = initialWizardStrategy(
        settings.data.effective_defaults,
        spaceId,
        files,
      );
      return {
        ...previous,
        rules: {
          ...previous.rules,
          fileList: seeded.rules.fileList.map(
            (file) =>
              previous.rules.fileList.find((old) => old.id === file.id) ?? file,
          ),
        },
      };
    });
    setStep(2);
  };
  const handleCommit = (direct: boolean) => {
    if (!settings.data) return;
    const chosen = direct
      ? initialWizardStrategy(settings.data.effective_defaults, spaceId, files)
      : strategy;
    if (!chosen || previewBusy.current) return;
    try {
      const rules = Object.fromEntries(
        files.map((file) => [
          file.file_path,
          wizardOverrides(chosen, file.file_path),
        ]),
      );
      if (
        !direct &&
        files.some(
          (file) =>
            book[file.id] &&
            (book[file.id].value.status !== "completed" ||
              book[file.id].fingerprint !==
                JSON.stringify(rules[file.file_path])),
        )
      ) {
        invalidRules();
        return;
      }
      if (
        queue.commit(
          direct ? "direct" : "previewed",
          (path) => rules[path],
          book,
        )
      )
        setStep(4);
    } catch {
      invalidRules();
    }
  };
  return (
    <section
      aria-label={t("uploadFile")}
      className="flex h-full min-h-0 flex-col gap-6 p-4"
    >
      <header className="flex flex-wrap items-center gap-6">
        {onBack && (
          <Button variant="text" onClick={onBack}>
            {t("backToKnowledge")}
          </Button>
        )}
        <StepProgress
          currentStep={step}
          align="center"
          className="flex-1"
          labels={[
            t("uploadFile"),
            t("segmentStrategy"),
            t("textComparison"),
            t("dataProcessing"),
          ]}
        />
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        {step === 1 && (
          <div className="mx-auto w-full max-w-[1450px] space-y-4 py-4">
            <DropZone onDrop={queue.handleDrop} />
            <Button
              variant="outlined"
              onClick={() => folderInput.current?.click()}
            >
              {t("f118.upload_folder")}
            </Button>
            <input
              type="file"
              multiple
              className="hidden"
              aria-label={t("f118.upload_folder")}
              ref={folderInput}
              {...{ webkitdirectory: "", directory: "" }}
              onChange={(event) => {
                queue.handleFolder(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
            {settings.isError ? (
              <div role="alert">
                <p>{t("f118.load_failed")}</p>
                <Button
                  onClick={() => {
                    void settings.refetch();
                  }}
                >
                  {t("retry")}
                </Button>
              </div>
            ) : (
              !settings.data && (
                <p role="status">{t("f118.loading_defaults")}</p>
              )
            )}
            <SpaceUploadProgress
              jobs={queue.jobs}
              observed={queue.observed}
              unavailable={queue.unavailable}
              onCancel={queue.handleCancel}
              onRetry={queue.retry}
              onRemove={queue.remove}
            />
          </div>
        )}
        {step === 2 && (
          <p className="text-sm text-text-secondary">
            {t("f118.upload_rules_hint")}
          </p>
        )}
        {step === 2 && strategy && (
          <FileUploadStep2
            step={2}
            kId={spaceId}
            resultFiles={files}
            isSubmitting={busy}
            persistState={strategy}
            onPersistStateChange={handleStrategy}
            onPrev={() => setStep(1)}
            onNext={() => {
              try {
                files.forEach((file) =>
                  wizardOverrides(strategy, file.file_path),
                );
                setStep(3);
              } catch {
                invalidRules();
              }
            }}
            previewRenderer={(value) => (
              <SpaceUploadPreview
                scope={scope}
                spaceId={spaceId}
                strategy={{ ...strategy, ...value }}
                book={book}
                onPreview={handlePreview}
                onBusy={handleBusy}
                previewCount={value.previewCount}
              />
            )}
          />
        )}
        {step === 3 && strategy && (
          <SpaceUploadPreview
            scope={scope}
            spaceId={spaceId}
            strategy={strategy}
            book={book}
            onPreview={handlePreview}
            onBusy={handleBusy}
            editable
          />
        )}
        {step === 4 && (
          <SpaceUploadProgress
            jobs={queue.jobs}
            observed={queue.observed}
            unavailable={queue.unavailable}
            onCancel={queue.handleCancel}
            onRetry={queue.retry}
          />
        )}
        {step === 4 && queue.unavailable && (
          <Button
            onClick={() => {
              void queue.retryStatus();
            }}
          >
            {t("retry")}
          </Button>
        )}
      </div>
      {step !== 2 && (
        <footer className="flex justify-center gap-4 border-t py-4">
          {step === 1 && (
            <>
              <Button
                variant="outlined"
                disabled={!ready}
                onClick={() => handleCommit(true)}
              >
                {t("uploadDirectly")}
              </Button>
              <Button disabled={!ready} onClick={handleNext}>
                {t("nextStep")}
              </Button>
            </>
          )}
          {step === 3 && (
            <>
              <Button
                variant="outlined"
                disabled={busy}
                onClick={() => setStep(2)}
              >
                {t("previousStep")}
              </Button>
              <Button
                disabled={
                  busy ||
                  book[files[0]?.id]?.value.status !== "completed" ||
                  files.some(
                    (file) =>
                      book[file.id] &&
                      book[file.id].value.status !== "completed",
                  )
                }
                onClick={() => handleCommit(false)}
              >
                {t("nextStep")}
              </Button>
            </>
          )}
          {step === 4 && onBack && (
            <Button onClick={onBack}>{t("backToKnowledge")}</Button>
          )}
        </footer>
      )}
    </section>
  );
}
