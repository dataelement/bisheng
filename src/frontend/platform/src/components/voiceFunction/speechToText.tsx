import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Mic, Square, Loader, LoaderCircle, Ellipsis } from 'lucide-react';
import i18next from "i18next";
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { speechToText } from '@/controllers/API/workbench';
import VoiceRecordingIcon from '../bs-ui/voice';

// --- 核心音频处理逻辑 ---
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

// --- 主组件---
const SpeechToTextComponent = ({ onChange }) => {
  const [version] = useState(window.chat_version || 'v1');
  const { toast } = useToast();
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [recordDuration, setRecordDuration] = useState(0); // 录音时长（秒）
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioContextRef = useRef(null);
  const timerRef = useRef(null); // 定时器引用
  const maxRecordTime = 600; // 最大录音时长：10分钟 = 600秒

  // 格式化时长为 "MM:SS" 格式
  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // 开始录音（添加10分钟限制逻辑）
  const startRecording = async () => {
    try {
      audioChunksRef.current = [];
      setIsProcessing(false);
      setRecordDuration(0); // 重置时长

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
          // 清除定时器
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
        }
      };

      // 开始录音
      mediaRecorderRef.current.start();
      setIsRecording(true);

      // 启动定时器：每秒更新时长，到达10分钟自动停止
      timerRef.current = setInterval(() => {
        setRecordDuration(prev => {
          const newDuration = prev + 1;
          // 到达最大时长，自动停止录音
          if (newDuration >= maxRecordTime) {
            clearInterval(timerRef.current);
            timerRef.current = null;
            stopRecording();
            // 提示用户已达最大时长
            toast({
              title: i18next.t('prompt'),
              variant: 'info',
              description: '已达到最大录音时长（10分钟），录音已自动停止'
            });
          }
          return newDuration;
        });
      }, 600000);

    } catch (err) {
      toast({
        title: i18next.t('prompt'),
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
      // 清除定时器
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  };

  // 组件卸载时清理资源
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      if (mediaRecorderRef.current?.stream) {
        mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, []);

  // 语音转文字API
  const convertSpeechToText = async (audioBlob) => {
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.wav');

      // 直接调用API，不要使用captureAndAlertRequestErrorHoc
      const res = await speechToText(formData, version);

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

  //绝对定位、按钮布局、pulse-ring ---
  return (
    <div className="relative z-10">
      {/* right-12 top-5 绝对定位 */}
      <div className="absolute right-12 top-5 cursor-pointer">
        {isProcessing && (
          <LoaderCircle className="animate-spin" />
        )}
        {!isProcessing && isRecording && (
          <VoiceRecordingIcon size={18} onClick={stopRecording} />
        )}
        {!isProcessing && !isRecording && (
          <Mic size={18} onClick={startRecording} />
        )}
      </div>

      {isRecording && <div className="pulse-ring"></div>}
    </div>
  );
};

// 类型定义
SpeechToTextComponent.propTypes = {
  onChange: PropTypes.func.isRequired
};

export default SpeechToTextComponent;