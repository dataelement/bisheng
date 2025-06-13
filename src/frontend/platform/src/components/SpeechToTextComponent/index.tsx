import React, { useState, useRef } from 'react';
import PropTypes from 'prop-types';
import { Mic, Square, Loader } from 'lucide-react';
import i18next from "i18next";
import { speechToText, textToSpeech, uploadAndStt, uploadChatFile } from '@/controllers/API/flow';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useToast } from "@/components/bs-ui/toast/use-toast";
const SpeechToTextComponent = ({ onChange }) => {
  const { toast } = useToast()
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // 开始录音
  const startRecording = async () => {
    try {
      setError(null);
      audioChunksRef.current = [];
      
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      
      mediaRecorderRef.current.ondataavailable = (event) => {
        audioChunksRef.current.push(event.data);
      };
      
      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await convertSpeechToText(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
      
      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      toast({
        title: `${i18next.t('prompt')}`,
        variant: 'error',
        description: '麦克风未授权'
      });
    }
  };

  // 停止录音
  const stopRecording = () => {
    if (isProcessing) return;
    if (mediaRecorderRef.current && isRecording) {
      setIsProcessing(true);
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  // 调用语音转文字API
  const convertSpeechToText = async (audioBlob) => {
    try {
      // 语音转文字API调用
      console.log('文件', audioBlob);
      uploadChatFile(audioBlob, () => {})
      const res = await captureAndAlertRequestErrorHoc(uploadAndStt(audioBlob, (progress) => {}));
      const mockTranscript = res?.text || '';
      onChange(mockTranscript);
    } catch (err) {
      toast({
        title: `${i18next.t('prompt')}`,
        variant: 'error',
        description: '语音识别失败'
      });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="relative z-10">
      <div className="absolute right-12 top-5 cursor-pointer">
        {isProcessing && (
          <Loader size={18} />
        )}
        {!isProcessing && isRecording && (
          <Square size={18} onClick={stopRecording}/>
        )}
        {!isProcessing && !isRecording && (
          <Mic size={18} onClick={startRecording}/>
        )}
      </div>
      {isRecording && <div className="pulse-ring"></div>}
    </div>
  );
};

SpeechToTextComponent.propTypes = {
  onChange: PropTypes.func.isRequired
};

export default SpeechToTextComponent;