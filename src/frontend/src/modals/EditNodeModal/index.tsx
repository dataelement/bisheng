import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CodeAreaComponent from "../../components/codeAreaComponent";
import Dropdown from "../../components/dropdownComponent";
import FloatComponent from "../../components/floatComponent";
import InputComponent from "../../components/inputComponent";
import InputFileComponent from "../../components/inputFileComponent";
import InputListComponent from "../../components/inputListComponent";
import IntComponent from "../../components/intComponent";
import PromptAreaComponent from "../../components/promptComponent";
import TextAreaComponent from "../../components/textAreaComponent";
import ToggleShadComponent from "../../components/toggleShadComponent";
import { Badge } from "../../components/bs-ui/badge";
import { Button } from "../../components/bs-ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/bs-ui/dialog";
import EditLabel from "../../components/ui/editLabel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/bs-ui/table";
import { PopUpContext } from "../../contexts/popUpContext";
import { TabsContext } from "../../contexts/tabsContext";
import { typesContext } from "../../contexts/typesContext";
import { NodeDataType } from "../../types/flow";
import { classNames, limitScrollFieldsModal } from "../../utils";
import { useToast } from "@/components/bs-ui/toast/use-toast";

export default function EditNodeModal({ data }: { data: NodeDataType }) {
  const [open, setOpen] = useState(true);
  const [nodeLength, setNodeLength] = useState(
    Object.keys(data.node.template).filter(
      (t) =>
        t.charAt(0) !== "_" &&
        data.node.template[t].show &&
        (data.node.template[t].type === "str" ||
          data.node.template[t].type === "bool" ||
          data.node.template[t].type === "float" ||
          data.node.template[t].type === "code" ||
          data.node.template[t].type === "prompt" ||
          data.node.template[t].type === "file" ||
          data.node.template[t].type === "int")
    ).length
  );
  const [nodeValue, setNodeValue] = useState(null);
  const { closePopUp } = useContext(PopUpContext);
  const { types } = useContext(typesContext);
  const ref = useRef();
  const { isOnlineVersion, version, setTabsState, flow } = useContext(TabsContext);
  const { reactFlowInstance } = useContext(typesContext);

  let disabled =
    reactFlowInstance?.getEdges().some((e) => e.targetHandle === data.id) ??
    false;
  if (nodeLength == 0) {
    closePopUp();
  }

  function setModalOpen(x: boolean) {
    setOpen(x);
    if (x === false) {
      closePopUp();
    }
  }

  const { message } = useToast()
  const handleSave = () => {
    if (isOnlineVersion()) return message({
      title: '提示',
      description: '上线中不可编辑保存',
      variant: 'warning'
    })
    setModalOpen(false)
  }

  function changeAdvanced(node) {
    Object.keys(data.node.template).map((n, i) => {
      if (n === node.name) {
        data.node.template[n].advanced = !data.node.template[n].advanced;
      }
      return n;
    });
    setNodeValue(!nodeValue);
  }

  const handleOnNewValue = (newValue: any, name) => {
    data.node.template[name].value = newValue;
    // 手动修改知识库，collection_id 清空
    if (['index_name', 'collection_name'].includes(name)) delete data.node.template[name].collection_id
    // Set state to pending
    setTabsState((prev) => {
      return {
        ...prev,
        [flow.id]: {
          ...prev[flow.id],
          isPending: true,
        },
      };
    });
  };

  const idArr = data.id.split('-')
  const handleChangeId = (id) => {
    const oldId = data.id
    const newId = `${idArr[0]}-${id}`
    document.dispatchEvent(new CustomEvent('idChange', { detail: [newId, oldId] }))
    setOpen(!open)
  }

  const { t } = useTranslation()
  return (
    <Dialog open={true} onOpenChange={setModalOpen}>
      <DialogTrigger asChild></DialogTrigger>
      <DialogContent className="sm:max-w-[740px] lg:max-w-[740px]">
        <DialogHeader>
          <DialogTitle className="flex items-center">
            <span className="pr-2">{data.type}</span>
            <Badge variant="secondary">ID:{idArr[0]}-
              <EditLabel
                rule={[
                  {
                    // 正则字母和数字 5 位数
                    pattern: /^[a-zA-Z0-9]{5}$/,
                    message: t('flow.incorrectIdFormatMessage'),
                  },
                  {
                    // required: true,
                    // 自定义函数校验
                    validator: (val) => {
                      const node = window._flow.data.nodes.find((node) =>
                        node.data.id.split('-')[1] === val &&
                        node.data.id !== data.id // 排除self
                      )
                      return !node
                    },
                    message: t('flow.idAlreadyExistsMessage'),
                  }
                ]}
                str={idArr[1]}
                onChange={handleChangeId}>
                {(val) => <>{val}</>}
              </EditLabel>
            </Badge>
          </DialogTitle>
          <DialogDescription asChild>
            <div>
              {data.node?.description}
              <div className="flex pt-3">
                {/* <Variable className="edit-node-modal-variable "></Variable> */}
                <span className="edit-node-modal-span">List</span>
              </div>
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="edit-node-modal-arrangement">
          <div
            className={classNames(
              "edit-node-modal-box",
              nodeLength > limitScrollFieldsModal
                ? "overflow-scroll overflow-x-hidden custom-scroll"
                : "overflow-hidden"
            )}
          >
            {nodeLength > 0 && (
              <div className="edit-node-modal-table">
                <Table className="table-fixed bg-muted outline-1">
                  <TableHeader className="edit-node-modal-table-header">
                    <TableRow className="">
                      <TableHead className="h-7 text-center">parameter</TableHead>
                      <TableHead className="h-7 p-0 text-center">value</TableHead>
                      <TableHead className="h-7 text-center">show</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody className="p-0">
                    {Object.keys(data.node.template)
                      .filter(
                        (t) =>
                          t.charAt(0) !== "_" &&
                          data.node.template[t].show &&
                          (data.node.template[t].type === "str" ||
                            data.node.template[t].type === "bool" ||
                            data.node.template[t].type === "float" ||
                            data.node.template[t].type === "code" ||
                            data.node.template[t].type === "prompt" ||
                            data.node.template[t].type === "file" ||
                            data.node.template[t].type === "int" ||
                            data.node.template[t].type === "dict")
                      )
                      .map((n, i) => (
                        <TableRow key={i} className="h-10">
                          <TableCell className="truncate p-0 text-center text-sm text-foreground sm:px-3">
                            {data.node.template[n].name
                              ? data.node.template[n].name
                              : data.node.template[n].display_name}
                          </TableCell>
                          <TableCell className="w-[300px] p-0 text-center text-xs text-foreground ">
                            {data.node.template[n].type === "str" &&
                              !data.node.template[n].options ? (
                              <div className="mx-auto">
                                {data.node.template[n].list ? (
                                  <InputListComponent
                                    editNode={true}
                                    disabled={disabled}
                                    value={
                                      !data.node.template[n].value ||
                                        data.node.template[n].value === ""
                                        ? [""]
                                        : data.node.template[n].value
                                    }
                                    onChange={(t: string[]) => {
                                      handleOnNewValue(t, n);
                                    }}
                                  />
                                ) : data.node.template[n].multiline ? (
                                  <TextAreaComponent
                                    disabled={disabled}
                                    editNode={true}
                                    value={data.node.template[n].value ?? ""}
                                    onChange={(t: string) => {
                                      handleOnNewValue(t, n);
                                    }}
                                  />
                                ) : (
                                  <InputComponent
                                    editNode={true}
                                    disabled={disabled}
                                    password={
                                      data.node.template[n].password ?? false
                                    }
                                    value={data.node.template[n].value ?? ""}
                                    onChange={(t) => {
                                      handleOnNewValue(t, n);
                                    }}
                                  />
                                )}
                              </div>
                            ) : data.node.template[n].type === "bool" ? (
                              <div className="ml-auto">
                                {" "}
                                <ToggleShadComponent
                                  disabled={disabled}
                                  enabled={data.node.template[n].value}
                                  setEnabled={(t) => {
                                    handleOnNewValue(t, n);
                                  }}
                                  size="small"
                                />
                              </div>
                            ) : data.node.template[n].type === "float" ? (
                              <div className="mx-auto">
                                <FloatComponent
                                  disabled={disabled}
                                  editNode={true}
                                  value={data.node.template[n].value ?? ""}
                                  onChange={(t) => {
                                    data.node.template[n].value = t;
                                  }}
                                />
                              </div>
                            ) : data.node.template[n].type === "str" &&
                              data.node.template[n].options ? (
                              <div className="mx-auto">
                                <Dropdown
                                  numberOfOptions={nodeLength}
                                  editNode={true}
                                  options={data.node.template[n].options}
                                  onSelect={(t) => handleOnNewValue(t, n)}
                                  value={
                                    data.node.template[n].value ??
                                    "Choose an option"
                                  }
                                ></Dropdown>
                              </div>
                            ) : data.node.template[n].type === "int" ? (
                              <div className="mx-auto">
                                <IntComponent
                                  disabled={disabled}
                                  editNode={true}
                                  value={data.node.template[n].value ?? ""}
                                  onChange={(t) => {
                                    handleOnNewValue(t, n);
                                  }}
                                />
                              </div>
                            ) : data.node.template[n].type === "file" ? (
                              <div className="mx-auto">
                                <InputFileComponent
                                  editNode={true}
                                  disabled={disabled}
                                  value={data.node.template[n].value ?? ""}
                                  onChange={(t: string) => {
                                    handleOnNewValue(t, n);
                                  }}
                                  fileTypes={data.node.template[n].fileTypes}
                                  suffixes={data.node.template[n].suffixes}
                                  onFileChange={(t: string) => {
                                    handleOnNewValue(t, n);
                                  }}
                                ></InputFileComponent>
                              </div>
                            ) : data.node.template[n].type === "prompt" ? (
                              <div className="mx-auto">
                                <PromptAreaComponent
                                  field_name={n}
                                  editNode={true}
                                  disabled={disabled}
                                  nodeClass={data.node}
                                  setNodeClass={(nodeClass) => {
                                    data.node = nodeClass;
                                  }}
                                  value={data.node.template[n].value ?? ""}
                                  onChange={(t: string) => {
                                    handleOnNewValue(t, n);
                                  }}
                                />
                              </div>
                            ) : data.node.template[n].type === "code" ? (
                              <div className="mx-auto">
                                <CodeAreaComponent
                                  disabled={disabled}
                                  editNode={true}
                                  value={data.node.template[n].value ?? ""}
                                  onChange={(t: string) => {
                                    handleOnNewValue(t, n);
                                  }}
                                />
                              </div>
                            ) : data.node.template[n].type === "Any" ? (
                              "-"
                            ) : (
                              <div className="hidden"></div>
                            )}
                          </TableCell>
                          <TableCell className="p-0 text-right">
                            <div className="items-center text-center">
                              <ToggleShadComponent
                                enabled={!data.node.template[n].advanced}
                                setEnabled={(e) =>
                                  changeAdvanced(data.node.template[n])
                                }
                                disabled={disabled}
                                size="small"
                              />
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button className="mt-3 rounded-full" onClick={handleSave} type="submit" >save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
