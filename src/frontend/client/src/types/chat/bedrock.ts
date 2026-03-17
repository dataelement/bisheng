import { z } from 'zod';
import * as s from './schemas';

export const bedrockInputSchema = s.tConversationSchema
  .pick({
    modelLabel: true,
    promptPrefix: true,
    resendFiles: true,
    iconURL: true,
    greeting: true,
    spec: true,
    maxOutputTokens: true,
    maxContextTokens: true,
    artifacts: true,
    region: true,
    system: true,
    model: true,
    maxTokens: true,
    temperature: true,
    topP: true,
    stop: true,
    topK: true,
    additionalModelRequestFields: true,
  })
  .transform((obj) => s.removeNullishValues(obj))
  .catch(() => ({}));

export type BedrockConverseInput = z.infer<typeof bedrockInputSchema>;
