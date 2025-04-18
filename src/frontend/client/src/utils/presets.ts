import type { TPreset, TPlugin } from '~/data-provider/data-provider/src';
import { EModelEndpoint } from '~/data-provider/data-provider/src';

type TEndpoints = Array<string | EModelEndpoint>;

export const getPresetTitle = (preset: TPreset, mention?: boolean) => {
  const {
    endpoint,
    title: presetTitle,
    model,
    tools,
    promptPrefix,
    chatGptLabel,
    modelLabel,
  } = preset;
  const modelInfo = model ?? '';
  let title = '';
  let label = '';

  const usesChatGPTLabel: TEndpoints = [
    EModelEndpoint.azureOpenAI,
    EModelEndpoint.openAI,
    EModelEndpoint.custom,
  ];
  const usesModelLabel: TEndpoints = [EModelEndpoint.google, EModelEndpoint.anthropic];

  if (endpoint != null && endpoint && usesChatGPTLabel.includes(endpoint)) {
    label = chatGptLabel ?? '';
  } else if (endpoint != null && endpoint && usesModelLabel.includes(endpoint)) {
    label = modelLabel ?? '';
  }
  if (
    label &&
    presetTitle != null &&
    presetTitle &&
    label.toLowerCase().includes(presetTitle.toLowerCase())
  ) {
    title = label + ': ';
    label = '';
  } else if (presetTitle != null && presetTitle && presetTitle.trim() !== 'New Chat') {
    title = presetTitle + ': ';
  }

  if (mention === true) {
    return `${modelInfo}${label ? ` | ${label}` : ''}${
      promptPrefix != null && promptPrefix ? ` | ${promptPrefix}` : ''
    }${
      tools
        ? ` | ${tools
          .map((tool: TPlugin | string) => {
            if (typeof tool === 'string') {
              return tool;
            }
            return tool.pluginKey;
          })
          .join(', ')}`
        : ''
    }`;
  }

  return `${title}${modelInfo}${label ? ` (${label})` : ''}`.trim();
};

/** Remove unavailable tools from the preset */
export const removeUnavailableTools = (
  preset: TPreset,
  availableTools: Record<string, TPlugin | undefined>,
) => {
  const newPreset = { ...preset };

  if (newPreset.tools && newPreset.tools.length > 0) {
    newPreset.tools = newPreset.tools
      .filter((tool) => {
        let pluginKey: string;
        if (typeof tool === 'string') {
          pluginKey = tool;
        } else {
          ({ pluginKey } = tool);
        }

        return !!availableTools[pluginKey];
      })
      .map((tool) => {
        if (typeof tool === 'string') {
          return tool;
        }
        return tool.pluginKey;
      });
  }

  return newPreset;
};
