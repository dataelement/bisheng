import { DialogTitle } from "@radix-ui/react-dialog";
import "ace-builds/src-noconflict/ace";
import "ace-builds/src-noconflict/ext-language_tools";
import "ace-builds/src-noconflict/mode-python";
import "ace-builds/src-noconflict/theme-github";
import "ace-builds/src-noconflict/theme-twilight";
import { TerminalSquare } from "lucide-react";
import { useContext, useState } from "react";
import AceEditor from "react-ace";
import { Button } from "../../components/ui/button";
import { alertContext } from "../../contexts/alertContext";
import { darkContext } from "../../contexts/darkContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { postValidateCode } from "../../controllers/API";
import { APIClassType } from "../../types/api";
import BaseModal from "../baseModal";

export default function CodeAreaModal({
  value,
  setValue,
  nodeClass,
  setNodeClass,
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

  function setModalOpen(x: boolean) {
    if (x === false) {
      setCloseEdit("codearea");
      closePopUp();
    }
  }

  function handleClick() {
    postValidateCode(code)
      .then((apiReturn) => {
        if (apiReturn.data) {
          let importsErrors = apiReturn.data.imports.errors;
          let funcErrors = apiReturn.data.function.errors;
          if (funcErrors.length === 0 && importsErrors.length === 0) {
            setSuccessData({
              title: "代码准备运行",
            });
            setValue(code);
            setModalOpen(false);
          } else {
            if (funcErrors.length !== 0) {
              setErrorData({
                title: "您的函数中存在一个错误",
                list: funcErrors,
              });
            }
            if (importsErrors.length !== 0) {
              setErrorData({
                title: "您的导入有误",
                list: importsErrors,
              });
            }
          }
        } else {
          setErrorData({
            title: "出错了，请重试",
          });
        }
      })
      .catch((_) => {
        setErrorData({
          title: "这段代码有问题，请检查以下",
        });
      });
  }

  return (
    <BaseModal open={true} setOpen={setModalOpen}>
      <BaseModal.Header description={'编辑你的 Python 代码此代码片段接受模块导入和一个函数定义。确保您的函数返回一个字符串。'}>
        <DialogTitle className="flex items-center">
          <span className="pr-2">编辑代码</span>
          <TerminalSquare
            strokeWidth={1.5}
            className="h-6 w-6 pl-1 text-primary "
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
              检查 & 保存
            </Button>
          </div>
        </div>
      </BaseModal.Content>
    </BaseModal>
  );
}
