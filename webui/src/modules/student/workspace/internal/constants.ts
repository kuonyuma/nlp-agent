import type { UserSettings } from "@/shared/types";

export const DEFAULT_SETTINGS: UserSettings = {
  locale: "zh-CN",
  theme: "system",
  show_reasoning: false,
  stream_render_interval_ms: 30,
  model_profile: "deepseek",
};
