import axios from "../request";

export type SpeechToTextResponse = {
    text: string;
};

export type TextToSpeechResponse = {
    audio: string;
};

// 语音转文字
export const speechToText = (data: FormData): Promise<SpeechToTextResponse> => {
    return axios.post('/api/v1/llm/workbench/asr', data);
}

// 文字转语音
export const textToSpeech = (text: string): Promise<TextToSpeechResponse> => {
    // 对中文文本进行 URL 编码，确保参数传递正确
    const encodedText = encodeURIComponent(text);
    return axios.get(`/api/v1/llm/workbench/tts?text=${encodedText}`);
  };

