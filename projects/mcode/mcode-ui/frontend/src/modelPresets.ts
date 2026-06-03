export interface ModelPreset {
  id: string;
  label: string;
  model: "deepseek-v4-pro" | "deepseek-v4-flash";
  thinkingMode: boolean;
}

export const MODEL_PRESETS: ModelPreset[] = [
  {
    id: "deepseek-v4-pro",
    label: "DeepSeek-V4 Pro:deepseek-v4-pro",
    model: "deepseek-v4-pro",
    thinkingMode: false,
  },
  {
    id: "deepseek-v4-pro-thinking",
    label: "DeepSeek-V4 Pro:deepseek-v4-pro",
    model: "deepseek-v4-pro",
    thinkingMode: true,
  },
  {
    id: "deepseek-v4-flash",
    label: "DeepSeek-V4 Flash:deepseek-v4-flash",
    model: "deepseek-v4-flash",
    thinkingMode: false,
  },
  {
    id: "deepseek-v4-flash-thinking",
    label: "DeepSeek-V4 Flash:deepseek-v4-flash",
    model: "deepseek-v4-flash",
    thinkingMode: true,
  },
];

export function presetIdFor(model: string, thinkingMode: boolean): string {
  return MODEL_PRESETS.find((preset) => preset.model === model && preset.thinkingMode === thinkingMode)?.id || MODEL_PRESETS[2].id;
}

export function presetById(id: string): ModelPreset {
  return MODEL_PRESETS.find((preset) => preset.id === id) || MODEL_PRESETS[2];
}

