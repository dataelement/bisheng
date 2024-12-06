import { Eraser, TerminalSquare, Variable } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { alertContext } from "../../contexts/alertContext";
import { typesContext } from "../../contexts/typesContext";
import { sendAllProps } from "../../types/api";
import { ChatMessageType } from "../../types/chat";
import { FlowType } from "../../types/flow";
import { classNames, validateNodes } from "../../utils";
import ChatInput from "./chatInput";
import ChatMessage from "./chatMessage";

import cloneDeep from "lodash-es/cloneDeep";
import { useTranslation } from "react-i18next";
import { Badge } from "../../components/bs-ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/bs-ui/dialog";
import { Textarea } from "../../components/bs-ui/input";
import ToggleShadComponent from "../../components/toggleShadComponent";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "../../components/ui/accordion";
import { THOUGHTS_ICON } from "../../constants";
import { locationContext } from "../../contexts/locationContext";
import { TabsContext } from "../../contexts/tabsContext";

export default function FormModal({
  flow,
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: Function;
  flow: FlowType;
}) {
  const { tabsState, setTabsState } = useContext(TabsContext);
  const [chatValue, setChatValue] = useState(() => {
    try {
      const { formKeysData } = tabsState[flow.id];
      if (!formKeysData) {
        throw new Error("formKeysData is undefined");
      }
      const inputKeys = formKeysData.input_keys.filter(el => !el.type)[0] || {};
      const handleKeys = formKeysData.handle_keys;

      const keyToUse = Object.keys(inputKeys).find(
        (k) => !handleKeys.some((j) => j === k) && inputKeys[k] === ""
      );

      return inputKeys[keyToUse];
    } catch (error) {
      console.error(error);
      // return a sensible default or `undefined` if no default is possible
      return undefined;
    }
  });

  const [chatHistory, setChatHistory] = useState<ChatMessageType[]>([]);
  const { reactFlowInstance } = useContext(typesContext);
  const { setErrorData } = useContext(alertContext);
  const ws = useRef<WebSocket | null>(null);
  const [lockChat, setLockChat] = useState(false);
  const isOpen = useRef(open);
  const messagesRef = useRef(null);
  const id = useRef(flow.id);
  const tabsStateFlowId = tabsState[flow.id];
  const tabsStateFlowIdFormKeysData = tabsStateFlowId.formKeysData;
  const [chatKey, setChatKey] = useState(''
    // tabsState[flow.id].formKeysData.input_keys.find()
    // Object.keys(tabsState[flow.id].formKeysData.input_keys).find(
    //   (k) =>
    //     !tabsState[flow.id].formKeysData.handle_keys.some((j) => j === k) &&
    //     tabsState[flow.id].formKeysData.input_keys[k] === ""
    // )
  );

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [chatHistory]);

  useEffect(() => {
    isOpen.current = open;
  }, [open]);
  useEffect(() => {
    id.current = flow.id;
  }, [flow.id, tabsStateFlowId, tabsStateFlowIdFormKeysData]);

  var isStream = false;

  const addChatHistory = (
    message: string | Object,
    isSend: boolean,
    chatKey: string,
    template?: string,
    thought?: string,
    files?: Array<any>
  ) => {
    setChatHistory((old) => {
      let newChat = cloneDeep(old);
      if (files) {
        newChat.push({ message, isSend, files, thought, chatKey });
      } else if (thought) {
        newChat.push({ message, isSend, thought, chatKey });
      } else if (template) {
        newChat.push({ message, isSend, chatKey, template });
      } else {
        newChat.push({ message, isSend, chatKey });
      }
      return newChat;
    });
  };

  //add proper type signature for function

  function updateLastMessage({
    str,
    thought,
    end = false,
    files,
  }: {
    str?: string;
    thought?: string;
    // end param default is false
    end?: boolean;
    files?: Array<any>;
  }) {
    setChatHistory((old) => {
      if (!old.length) return old // 拒绝 chatHistory无数据时接收数据
      let newChat = [...old];
      let prevChat = newChat[newChat.length - 2]
      // let lastChat = newChat[newChat.length - 1]
      // 上一条log时，当前条与上一条合并(确保log在一条中)
      if (end && !prevChat?.message && prevChat?.thought) {
        prevChat.message += str || '';
        prevChat.thought += thought || '';
        newChat.pop()
        return newChat;
      }
      // 最后一条与上一条msg相同，合并处理
      if (end && str && newChat.length > 1 && str === prevChat.message) {
        newChat.pop()
        return newChat
      }
      // 过滤空消息
      if (end && !newChat[newChat.length - 1].message && !str) {
        newChat.pop()
        return newChat
      }
      if (str) {
        if (end) {
          newChat[newChat.length - 1].message = str;
        } else {
          newChat[newChat.length - 1].message =
            newChat[newChat.length - 1].message + str;
        }
      }
      if (thought) {
        newChat[newChat.length - 1].thought = thought;
      }
      if (files) {
        newChat[newChat.length - 1].files = files;
      }
      return newChat;
    });
  }

  function handleOnClose(event: CloseEvent) {
    if (isOpen.current) {
      setErrorData({ title: 'ws is close;' + event.reason });
      setTimeout(() => {
        // connectWS();
        setLockChat(false);
      }, 1000);
    }
  }

  const { appConfig } = useContext(locationContext)

  function getWebSocketUrl(chatId, isDevelopment = false) {
    const isSecureProtocol = window.location.protocol === "https:";
    const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
    const host = appConfig.websocketHost || window.location.host // isDevelopment ? "localhost:7860" : window.location.host;
    const chatEndpoint = `${__APP_ENV__.BASE_URL}/api/v1/chat/${chatId}`;

    const token = localStorage.getItem("ws_token") || '';
    return `${isDevelopment ? "ws" : webSocketProtocol
      }://${host}${chatEndpoint}?t=${token}`;
  }

  function handleWsMessage(data: any) {
    if (Array.isArray(data)) {
      //set chat history
      // setChatHistory((_) => {
      //   let newChatHistory: ChatMessageType[] = [];
      //   data.forEach(
      //     (chatItem: {
      //       intermediate_steps?: string;
      //       is_bot: boolean;
      //       message: string;
      //       template: string;
      //       type: string;
      //       chatKey: string;
      //       files?: Array<any>;
      //     }) => {
      //       if (chatItem.message) {
      //         newChatHistory.push(
      //           chatItem.files
      //             ? {
      //               isSend: !chatItem.is_bot,
      //               message: chatItem.message,
      //               template: chatItem.template,
      //               thought: chatItem.intermediate_steps,
      //               files: chatItem.files,
      //               chatKey: chatItem.chatKey,
      //             }
      //             : {
      //               isSend: !chatItem.is_bot,
      //               message: chatItem.message,
      //               template: chatItem.template,
      //               thought: chatItem.intermediate_steps,
      //               chatKey: chatItem.chatKey,
      //             }
      //         );
      //       }
      //     }
      //   );
      //   return newChatHistory;
      // });
      return []
    }
    if (data.type === "start") {
      addChatHistory("", false, chatKey);
      isStream = true;
    }
    if (data.type === "end") {
      if (data.message) {
        updateLastMessage({ str: data.message, end: true });
      }
      if (data.intermediate_steps) {
        updateLastMessage({
          str: data.message,
          thought: data.intermediate_steps,
          end: true,
        });
      }
      if (data.files) {
        updateLastMessage({
          end: true,
          files: data.files,
        });
      }

      setLockChat(false);
      isStream = false;
    }
    if (data.type === "stream" && isStream) {
      updateLastMessage({ str: data.message, thought: data.intermediate_steps });
    }
  }

  function connectWS() {
    try {
      const urlWs = getWebSocketUrl(
        id.current,
        process.env.NODE_ENV === "development"
      );
      const newWs = new WebSocket(urlWs);
      newWs.onopen = () => {
        console.log("WebSocket connection established!");
      };
      newWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWsMessage(data);
        //get chat history
      };
      newWs.onclose = (event) => {
        handleOnClose(event);
      };
      newWs.onerror = (ev) => {
        console.log(ev, "error");
        if (flow.id === "") {
          // connectWS();
        } else {
          setErrorData({
            title: "Network connection error, please try the following methods:",
            list: [
              "Refresh the page.",
              "Use a new flow tab.",
              "Check if the background is running."
            ],
          });
        }
      };
      ws.current = newWs;
    } catch (error) {
      if (flow.id === "") {
        // connectWS();
      }
      console.log(error);
    }
  }

  useEffect(() => {
    connectWS();
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
    // do not add connectWS on dependencies array
  }, []);

  useEffect(() => {
    if (
      ws.current &&
      (ws.current.readyState === ws.current.CLOSED ||
        ws.current.readyState === ws.current.CLOSING)
    ) {
      connectWS();
      setLockChat(false);
    }
    // do not add connectWS on dependencies array
  }, [lockChat]);

  async function sendAll(data: sendAllProps) {
    try {
      if (ws) {
        ws.current.send(JSON.stringify(data));
      }
    } catch (error) {
      setErrorData({
        title: "There was an error sending the message",
        list: [error.message],
      });
      setChatValue(data.inputs);
      connectWS();
    }
  }

  // 消息滚动
  useEffect(() => {
    // if (ref.current) ref.current.scrollIntoView({ behavior: "smooth" }); // iframe会影响父级滚动
  }, [chatHistory]);

  const ref = useRef(null);

  useEffect(() => {
    if (open && ref.current) {
      ref.current.focus();
    }
  }, [open]);

  function sendMessage() {
    let nodeValidationErrors = validateNodes(reactFlowInstance);
    if (nodeValidationErrors.length === 0) {
      let inputs: any = tabsState[id.current].formKeysData.input_keys;
      inputs = inputs.find((el: any) => !el.type) || {}
      // const chatKey = Object.keys(inputs)[0];

      // if (!chatKey) return setErrorData({ title: "提示", list: ["至少选择一个inputkey"] });
      // if (!inputs[chatKey]) return setErrorData({ title: "提示", list: ["所选inputkey的值不能为空"] });
      setLockChat(true);
      const message = inputs;
      addChatHistory(
        message,
        true,
        chatKey,
        tabsState[flow.id].formKeysData.template
      );
      sendAll({
        ...reactFlowInstance.toObject(),
        flow_id: flow.id,
        inputs: inputs,
        chatHistory,
        name: flow.name,
        description: flow.description,
      });
      setTabsState((old) => {
        if (!chatKey) return old;
        let newTabsState = cloneDeep(old);
        // newTabsState[id.current].formKeysData.input_keys[chatKey] = "";
        return newTabsState;
      });
      setChatValue("");
    } else {
      setErrorData({
        title: "Oops! Looks like you missed some required information:",
        list: nodeValidationErrors,
      });
    }
  }
  function clearChat() {
    setChatHistory([]);
    ws.current.send(JSON.stringify({ clear_history: true }));
    if (lockChat) setLockChat(false);
  }

  function setModalOpen(x: boolean) {
    setOpen(x);
  }

  function handleOnCheckedChange(checked: boolean, i: string) {
    if (checked === true) {
      setChatKey(i);
      const input = tabsState[flow.id].formKeysData.input_keys.find((el: any) => !el.type) || {}
      setChatValue(input[i]);
    } else {
      setChatKey(null);
      setChatValue("");
    }
  }

  const input_keys = useMemo(() => {
    return tabsState[flow.id].formKeysData.input_keys.find((el: any) => !el.type) || {}
  }, [tabsState])

  const { t } = useTranslation()

  return (
    <Dialog open={open} onOpenChange={setModalOpen}>
      <DialogTrigger className="hidden"></DialogTrigger>
      {tabsState[flow.id].formKeysData && (
        <DialogContent className="min-w-[80vw]">
          <DialogHeader>
            <DialogTitle className="flex items-center">
              <span className="pr-2">Chat</span>
              <TerminalSquare
                className="h-6 w-6 pl-1 text-gray-800 dark:text-white"
                aria-hidden="true"
              />
            </DialogTitle>
            <DialogDescription>{t('chat.chatDialogTip')}</DialogDescription>
          </DialogHeader>

          <div className="form-modal-iv-box ">
            <div className="form-modal-iv-size">
              <div className="file-component-arrangement">
                <Variable className=" file-component-variable"></Variable>
                <span className="file-component-variables-span text-md">
                  Input Variables
                </span>
              </div>
              <div className="file-component-variables-title">
                <div className="file-component-variables-div">
                  <span className="text-sm font-medium text-primary">Name</span>
                </div>
                <div className="file-component-variables-div">
                  <span className="text-sm font-medium text-primary">
                    Chat Input
                  </span>
                </div>
              </div>
              <Accordion type="multiple" className="w-full">
                {Object.keys(input_keys).map(
                  (i, k) => (
                    <div className="file-component-accordion-div" key={k}>
                      <AccordionItem className="w-full" key={k} value={i}>
                        <AccordionTrigger className="flex gap-2">
                          <div className="file-component-badge-div">
                            <Badge variant="gray" size="md">
                              {i}
                            </Badge>

                            <div
                              className="-mb-1"
                              onClick={(event) => {
                                event.stopPropagation();
                              }}
                            >
                              <ToggleShadComponent
                                enabled={chatKey === i}
                                setEnabled={(value) =>
                                  handleOnCheckedChange(value, i)
                                }
                                size="small"
                                disabled={tabsState[
                                  id.current
                                ].formKeysData.handle_keys.some((t) => t === i)}
                              />
                            </div>
                          </div>
                        </AccordionTrigger>
                        <AccordionContent>
                          <div className="file-component-tab-column">
                            {tabsState[
                              id.current
                            ].formKeysData.handle_keys.some((t) => t === i) && (
                                <div className="font-normal text-muted-foreground ">
                                  Source: Component
                                </div>
                              )}
                            <Textarea
                              value={
                                input_keys[i]
                              }
                              onChange={(e) => {
                                setTabsState((old) => {
                                  let newTabsState = cloneDeep(old);
                                  const input = newTabsState[id.current].formKeysData.input_keys.find((el: any) => !el.type) || {}
                                  input[i] = e.target.value;
                                  return newTabsState;
                                });
                              }}
                              disabled={chatKey === i}
                              placeholder="Enter text..."
                            ></Textarea>
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    </div>
                  )
                )}
                {tabsState[id.current].formKeysData.memory_keys.map((i, k) => (
                  <AccordionItem key={k} value={i}>
                    <div className="tab-accordion-badge-div group">
                      <div className="group-hover:underline">
                        <Badge size="md" variant="gray">
                          {i}
                        </Badge>
                      </div>
                      Used as memory key
                    </div>
                  </AccordionItem>
                ))}
              </Accordion>
            </div>
            <div className="eraser-column-arrangement">
              <div className="eraser-size">
                <div className="eraser-position">
                  <button disabled={lockChat} onClick={() => clearChat()}>
                    <Eraser
                      className={classNames(
                        "h-5 w-5",
                        lockChat
                          ? "animate-pulse text-primary"
                          : "text-primary hover:text-gray-600"
                      )}
                      aria-hidden="true"
                    />
                  </button>
                </div>
                <div ref={messagesRef} className="chat-message-div">
                  {chatHistory.length > 0 ? (
                    chatHistory.map((c, i) => (
                      <ChatMessage
                        lockChat={lockChat}
                        chat={c}
                        lastMessage={
                          chatHistory.length - 1 === i ? true : false
                        }
                        key={i}
                      />
                    ))
                  ) : (
                    <div className="chat-alert-box">
                      <span>
                        👋{" "}
                      </span>
                      <br />
                      <div className="bisheng-chat-desc">
                        <span className="bisheng-chat-desc-span">
                          Start the conversation and click on the agent's analysis process{" "}
                          <span>
                            <THOUGHTS_ICON className="mx-1 inline h-5 w-5 animate-bounce " />
                          </span>{" "}
                          to inspect the linking process.。
                        </span>
                      </div>
                    </div>
                  )}
                  <div ref={ref}></div>
                </div>
                <div className="bisheng-chat-input-div">
                  <div className="bisheng-chat-input">
                    <ChatInput
                      chatValue={chatValue}
                      noInput={!chatKey}
                      lockChat={lockChat}
                      sendMessage={sendMessage}
                      setChatValue={(value) => {
                        setChatValue(value);
                        setTabsState((old) => {
                          let newTabsState = cloneDeep(old);
                          const input = newTabsState[id.current].formKeysData.input_keys.find((el: any) => !el.type) || {}
                          input[chatKey] = value;
                          return newTabsState;
                        });
                      }}
                      inputRef={ref}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
