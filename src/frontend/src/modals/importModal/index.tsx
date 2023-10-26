import {
  ArrowLeftIcon,
  ArrowUpTrayIcon,
  ComputerDesktopIcon,
  DocumentDuplicateIcon,
} from "@heroicons/react/24/outline";
import { useContext, useRef, useState } from "react";
import LoadingComponent from "../../components/loadingComponent";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "../../components/ui/dialog";
import { IMPORT_DIALOG_SUBTITLE } from "../../constants";
import { alertContext } from "../../contexts/alertContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { TabsContext } from "../../contexts/tabsContext";
import { getExamples } from "../../controllers/API";
import { FlowType } from "../../types/flow";
import { classNames } from "../../utils";
import ButtonBox from "./buttonBox";

export default function ImportModal() {
  const [open, setOpen] = useState(true);
  const { setErrorData } = useContext(alertContext);
  const { closePopUp } = useContext(PopUpContext);
  const ref = useRef();
  const [showExamples, setShowExamples] = useState(false);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [examples, setExamples] = useState<FlowType[]>([]);
  const { uploadFlow, addFlow } = useContext(TabsContext);
  function setModalOpen(x: boolean) {
    setOpen(x);
    if (x === false) {
      setTimeout(() => {
        closePopUp();
      }, 300);
    }
  }

  function handleExamples() {
    setLoadingExamples(true);
    getExamples()
      .then((result) => {
        setLoadingExamples(false);
        setExamples(result);
      })
      .catch((error) =>
        setErrorData({
          title: "An error occurred while loading the sample. Please try again.",
          list: [error.message],
        })
      );
  }

  return (
    <Dialog open={true} onOpenChange={setModalOpen}>
      <DialogTrigger></DialogTrigger>
      <DialogContent
        className={classNames(
          showExamples
            ? "h-[600px] lg:max-w-[650px]"
            : "h-[450px] lg:max-w-[650px]"
        )}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center">
            {showExamples && (
              <>
                <div className="dialog-header-modal-div">
                  <button
                    type="button"
                    className="dialog-header-modal-button disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground"
                    onClick={() => {
                      setShowExamples(false);
                    }}
                  >
                    <ArrowLeftIcon
                      className="ml-1 h-5 w-5 text-foreground"
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </>
            )}

            <span className={classNames(showExamples ? "pl-8 pr-2" : "pr-2")}>
              {showExamples ? "Select an example" : "Import"}
            </span>
            <ArrowUpTrayIcon
              className="ml-1 h-5 w-5 text-foreground"
              aria-hidden="true"
            />
          </DialogTitle>
          <DialogDescription>{IMPORT_DIALOG_SUBTITLE}</DialogDescription>
        </DialogHeader>

        <div
          className={classNames(
            "dialog-modal-examples-div",
            showExamples && !loadingExamples
              ? "dialog-modal-example-true"
              : "dialog-modal-example-false"
          )}
        >
          {!showExamples && (
            <div className="dialog-modal-button-box-div">
              <ButtonBox
                size="big"
                bgColor="bg-medium-emerald "
                description="Prebuilt Examples"
                icon={<DocumentDuplicateIcon className="document-icon" />}
                onClick={() => {
                  setShowExamples(true);
                  handleExamples();
                }}
                textColor="text-medium-emerald "
                title="Examples"
              ></ButtonBox>
              <ButtonBox
                size="big"
                bgColor="bg-almost-dark-blue "
                description="Import from Local"
                icon={<ComputerDesktopIcon className="document-icon" />}
                onClick={() => {
                  uploadFlow();
                  setModalOpen(false);
                }}
                textColor="text-almost-dark-blue "
                title="Local File"
              ></ButtonBox>
            </div>
          )}
          {showExamples && loadingExamples && (
            <div className="loading-component-div">
              <LoadingComponent remSize={30} />
            </div>
          )}
          {showExamples &&
            !loadingExamples &&
            examples.map((example, index) => {
              return (
                <div key={example.name} className="m-2">
                  {" "}
                  <ButtonBox
                    size="small"
                    bgColor="bg-medium-emerald "
                    description={example.description ?? "Prebuilt Examples"}
                    icon={
                      <DocumentDuplicateIcon
                        strokeWidth={1.5}
                        className="h-6 w-6 flex-shrink-0"
                      />
                    }
                    onClick={() => {
                      addFlow(example, false);
                      setModalOpen(false);
                    }}
                    textColor="text-medium-emerald "
                    title={example.name}
                  ></ButtonBox>
                </div>
              );
            })}
        </div>


      </DialogContent>
    </Dialog>
  );
}
