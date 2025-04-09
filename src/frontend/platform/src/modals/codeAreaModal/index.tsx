import { DialogTitle } from "@radix-ui/react-dialog";
import "ace-builds/src-noconflict/ace";
import "ace-builds/src-noconflict/ext-language_tools";
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-github";
import "ace-builds/src-noconflict/theme-twilight";
import { TerminalSquare } from "lucide-react";
import { useContext, useState } from "react";
import AceEditor from "react-ace";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/bs-ui/button";
import { alertContext } from "../../contexts/alertContext";
import { darkContext } from "../../contexts/darkContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { postValidateCode } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { APIClassType } from "../../types/api";
import BaseModal from "../baseModal";

export default function CodeAreaModal({
  value,
  setValue
}: {
  setValue: (value: string) => void;
  value: string;
  nodeClass: APIClassType;
  setNodeClass: (Class: APIClassType) => void;
}) {
  const [code, setCode] = useState(value);
  const { dark } = useContext(darkContext);
  const { closePopUp, setCloseEdit } = useContext(PopUpContext);
  const { setErrorData, setSuccessData } = useContext(alertContext);
  const { t } = useTranslation()

  function setModalOpen(x: boolean) {
    if (x === false) {
      setCloseEdit("codearea");
      closePopUp();
    }
  }

  function handleClick() {
    captureAndAlertRequestErrorHoc(postValidateCode(code)
      .then((apiReturn) => {
        if (apiReturn) {
          let importsErrors = apiReturn.imports.errors;
          let funcErrors = apiReturn.function.errors;
          if (funcErrors.length === 0 && importsErrors.length === 0) {
            setSuccessData({ title: t('code.codeReadyToRun') });
            setValue(code);
            setModalOpen(false);
          } else {
            if (funcErrors.length !== 0) {
              setErrorData({
                title: t('code.functionError'),
                list: funcErrors,
              });
            }
            if (importsErrors.length !== 0) {
              setErrorData({
                title: t('code.importsError'),
                list: importsErrors,
              });
            }
          }
        } else {
          setErrorData({
            title: t('code.errorOccurred'),
          });
        }
      }));
  }

  return (
    <BaseModal open={true} setOpen={setModalOpen}>
      <BaseModal.Header description={t('code.editPythonCodeDescription')}>
        <DialogTitle className="flex items-center">
          <span className="pr-2">{t('code.editCode')}</span>
          <TerminalSquare
            strokeWidth={1.5}
            className="h-6 w-6 pl-1 text-primary"
            aria-hidden="true"
          />
        </DialogTitle>
      </BaseModal.Header>
      <BaseModal.Content>
        <div className="flex h-full w-full flex-col transition-all">
          <div className="h-full w-full">
            <AceEditor
              value={code}
              mode="python"
              highlightActiveLine={true}
              showPrintMargin={false}
              fontSize={14}
              showGutter
              enableLiveAutocompletion
              theme={dark ? "twilight" : "github"}
              name="CodeEditor"
              onChange={(value) => {
                setCode(value);
              }}
              className="h-full w-full rounded-lg border-[1px] border-border custom-scroll"
            />
          </div>
          <div className="flex h-fit w-full justify-end">
            <Button className="mt-3" onClick={handleClick} type="submit">
              {t('code.checkAndSave')}
            </Button>
          </div>
        </div>
      </BaseModal.Content>
    </BaseModal>
  );
}

