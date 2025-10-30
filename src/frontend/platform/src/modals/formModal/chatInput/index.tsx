import { Lock, LucideSend, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { classNames } from "../../../utils";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import SpeechToTextComponent from "@/components/voiceFunction/speechToText";

export default function ChatInput({
  lockChat,
  chatValue,
  sendMessage,
  setChatValue,
  inputRef,
  noInput,
}) {
  const { data: linsightConfig } = useLinsightConfig();
  // 新增状态管理输入锁定状态
  const [inputLock, setInputLock] = useState({ locked: false });

  const handleSpeechRecognition = (text) => {
    console.log('识别到的文本:', text);
    
    // 修复未定义变量问题，完善锁定逻辑
    if (lockChat || inputLock.locked || !inputRef.current) return;
    
    // 将识别结果追加到当前输入框内容后
    const currentValue = inputRef.current.value;
    const newValue = currentValue + text;
    
    // 更新输入框内容并触发更新
    inputRef.current.value = newValue;
    setChatValue(newValue); // 同步更新外部状态
    
    // 触发input事件以更新UI（如自动调整高度）
    const event = new Event('input', { bubbles: true, cancelable: true });
    inputRef.current.dispatchEvent(event);
  };

  useEffect(() => {
    if (!lockChat && inputRef.current) {
      inputRef.current.focus();
    }
  }, [lockChat, inputRef]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "inherit"; // 重置高度
      // 自动调整高度以适应内容
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 150)}px`;
    }
  }, [chatValue, inputRef]);

  return (
    <div className="relative">
      <textarea
        onKeyDown={(event) => {
          if (event.key === "Enter" && !lockChat && !event.shiftKey) {
            sendMessage();
            event.preventDefault(); // 阻止默认换行行为
          }
        }}
        rows={1}
        ref={inputRef}
        disabled={lockChat || noInput}
        style={{
          resize: "none",
          maxHeight: "150px",
          overflow: inputRef.current && inputRef.current.scrollHeight > 150
            ? "auto"
            : "hidden"
        }}
        value={lockChat ? "Thinking..." : chatValue}
        onChange={(e) => {
          setChatValue(e.target.value);
        }}
        className={classNames(
          lockChat
            ? "form-modal-lock-true bg-input"
            : noInput
              ? "form-modal-no-input bg-input"
              : "form-modal-lock-false bg-background",
          "form-modal-lockchat"
        )}
        placeholder={
          noInput
            ? "cannot find a chat input entry. Click to run your skill."
            : "send message..."
        }
      />
      <div className="form-modal-send-icon-position">
        {/* 仅在有ASR模型配置时显示语音输入组件 */}
        <div   className={classNames(
            "form-modal-send-button",
          )}>  
          {linsightConfig?.asr_model?.id && (
          <SpeechToTextComponent onChange={handleSpeechRecognition} />
          )}
        </div>
        <button
          className={classNames(
            "form-modal-send-button",
            noInput
              ? "bg-indigo-600 text-background"
              : chatValue === ""
                ? "text-primary"
                : "bg-emerald-600 text-background"
          )}
          disabled={lockChat}
          onClick={() => sendMessage()}
        >
          {lockChat ? (
            <Lock className="form-modal-lock-icon" aria-hidden="true" />
          ) : noInput ? (
            <Sparkles className="form-modal-play-icon" aria-hidden="true" />
          ) : (
            <LucideSend className="form-modal-send-icon " aria-hidden="true" />
          )}
        </button>
      </div>
    </div>
  );
}