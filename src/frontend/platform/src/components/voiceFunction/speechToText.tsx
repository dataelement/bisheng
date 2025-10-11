import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Mic, Square, Loader } from 'lucide-react';
import i18next from "i18next";
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { speechToText } from '@/controllers/API/workbench';

// --- 核心音频处理逻辑（保留优化，不改动）---
const encodeWAV = (audioBuffer) => {
  const sampleRate = audioBuffer.sampleRate;
  const channels = audioBuffer.numberOfChannels;
  let samples = audioBuffer.getChannelData(0);

  // 多声道转单声道（降低杂音）
  if (channels > 1) {
    const monoSamples = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      let sum = 0;
      for (let c = 0; c < channels; c++) {
        sum += audioBuffer.getChannelData(c)[i];
      }
      monoSamples[i] = sum / channels;
    }
    samples = monoSamples;
  }

  // WAV文件头编码
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (view, offset, string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };

  // RIFF Chunk
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, 'WAVE');

  // fmt Chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);

  // data Chunk
  writeString(view, 36, 'data');
  view.setUint32(40, samples.length * 2, true);

  // 写入PCM数据
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    offset += 2;
  }

  return new Blob([view], { type: 'audio/wav' });
};

const convertBlobToWav = async (blob) => {
  return new Promise((resolve, reject) => {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 44100
    });
    const fileReader = new FileReader();

    fileReader.onload = async () => {
      try {
        const audioBuffer = await audioContext.decodeAudioData(fileReader.result);
        const wavBlob = encodeWAV(audioBuffer);
        resolve(wavBlob);
        audioContext.close();
      } catch (err) {
        reject(new Error("音频解码失败: " + err.message));
        audioContext.close();
      }
    };

    fileReader.onerror = () => {
      reject(new Error("读取音频文件失败"));
    };

    fileReader.readAsArrayBuffer(blob);
  });
};

// --- 主组件（还原原始样式结构）---
const SpeechToTextComponent = ({ onChange }) => {
  const { toast } = useToast();
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioContextRef = useRef(null);
  const timerRef = useRef(null);

  // 开始录音（保留优化参数，样式逻辑还原）
  const startRecording = async () => {
    try {
      audioChunksRef.current = [];
      setIsProcessing(false);

      // 优化的音频请求配置（保留降噪、高采样率）
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 44100,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      // 初始化AudioContext（用于优化编码）
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 44100
      });
      audioContextRef.current = audioContext;

      // 初始化MediaRecorder
      const options = { mimeType: 'audio/webm; codecs=opus' };
      mediaRecorderRef.current = new MediaRecorder(stream, options);

      // 收集录音数据
      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      // 录音停止处理
      mediaRecorderRef.current.onstop = async () => {
        try {
          setIsProcessing(true);
          const rawBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
          const wavBlob = await convertBlobToWav(rawBlob);
          await convertSpeechToText(wavBlob);
        } catch (conversionError) {
          console.error('音频转换失败:', conversionError);
          toast({
            title: i18next.t('prompt'),
            variant: 'error',
            description: '音频格式转换失败，请重试'
          });
        } finally {
          setIsProcessing(false);
          // 清理资源
          if (mediaRecorderRef.current?.stream) {
            mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
          }
          if (audioContextRef.current) {
            await audioContextRef.current.close();
          }
          if (timerRef.current) {
            clearInterval(timerRef.current);
          }
        }
      };

      // 开始录音
      mediaRecorderRef.current.start();
      setIsRecording(true);
    } catch (err) {
      toast({
        title: i18next.t('prompt'),
        variant: 'error',
        description: '麦克风未授权'
      });
    }
  };

  // 停止录音（逻辑还原）
  const stopRecording = () => {
    if (isProcessing) return;
    if (mediaRecorderRef.current && isRecording) {
      setIsProcessing(true);
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  // 语音转文字API（逻辑不变）
  const convertSpeechToText = async (audioBlob) => {
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.wav');
  
      // 直接调用API，不要使用captureAndAlertRequestErrorHoc
      const res = await speechToText(formData);
      
      // 解析返回的JSON数据
      const responseData = res.data || res;
      console.log('responseData', responseData);
      
      // 从data字段中获取识别文本
      const transcript = responseData || '';
      
      // 调用onChange回调，传递识别到的文本
      onChange(transcript);
      
    } catch (err) {
      toast({
        title: i18next.t('prompt'),
        variant: 'error',
        description: '语音识别失败'
      });
    } finally {
      setIsProcessing(false);
    }
  };

  // --- 还原原始样式结构：绝对定位、按钮布局、pulse-ring ---
  return (
    <div className="relative z-10">
      {/* 还原原始按钮位置：right-12 top-5 绝对定位 */}
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

      {/* 还原录音中脉冲样式（需确保全局CSS中有pulse-ring样式） */}
      {isRecording && <div className="pulse-ring"></div>}
    </div>
  );
};

// 类型定义（还原）
SpeechToTextComponent.propTypes = {
  onChange: PropTypes.func.isRequired
};

export default SpeechToTextComponent;