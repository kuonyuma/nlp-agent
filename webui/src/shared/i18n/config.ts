export const LOCALE_STORAGE_KEY = "pro-nlp.locale";

export const supportedLocales = [
  { code: "zh-CN", label: "Chinese (Simplified)", nativeLabel: "简体中文" },
  { code: "en", label: "English", nativeLabel: "English" },
] as const;

export type SupportedLocale = (typeof supportedLocales)[number]["code"];
export const defaultLocale: SupportedLocale = "zh-CN";
export const fallbackLocale: SupportedLocale = "en";

export function normalizeLocale(input: string | null | undefined): SupportedLocale {
  const value = input?.trim();
  if (!value) return defaultLocale;
  const exact = supportedLocales.find((locale) => locale.code === value);
  if (exact) return exact.code;
  const lower = value.toLowerCase();
  if (lower === "zh" || lower.startsWith("zh-cn") || lower.startsWith("zh-sg")) return "zh-CN";
  if (lower.startsWith("zh")) return "zh-CN";
  return supportedLocales.find((locale) => locale.code === lower.split("-")[0])?.code ?? defaultLocale;
}

export function persistLocale(locale: SupportedLocale) { try { localStorage.setItem(LOCALE_STORAGE_KEY, locale); } catch { /* storage is optional */ } }
export function resolveInitialLocale() { try { return normalizeLocale(localStorage.getItem(LOCALE_STORAGE_KEY) ?? navigator.language); } catch { return defaultLocale; } }
export function localeOption(locale: SupportedLocale) { return supportedLocales.find((item) => item.code === locale) ?? supportedLocales[0]; }
