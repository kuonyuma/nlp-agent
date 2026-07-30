import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { defaultLocale, fallbackLocale, normalizeLocale, persistLocale, resolveInitialLocale, type SupportedLocale } from "./config";

const zh = { common: { product: "NLP 学习助手", newChat: "新建对话", newCategory: "新建分类", search: "搜索", settings: "设置", uncategorized: "未分类", learningTopic: "学习主题", difficulty: "学习难度", teachingMode: "教学模式", readingLanguage: "阅读语言" } };
const en = { common: { product: "NLP Learning Assistant", newChat: "New chat", newCategory: "New category", search: "Search", settings: "Settings", uncategorized: "Uncategorized", learningTopic: "Learning topic", difficulty: "Difficulty", teachingMode: "Teaching mode", readingLanguage: "Reading language" } };

if (!i18n.isInitialized) void i18n.use(initReactI18next).init({ resources: { "zh-CN": zh, en }, lng: resolveInitialLocale(), fallbackLng: fallbackLocale, defaultNS: "common", interpolation: { escapeValue: false } });

export async function setAppLanguage(locale: SupportedLocale): Promise<void> { await i18n.changeLanguage(locale); }
i18n.on("languageChanged", (language) => { const locale = normalizeLocale(language); document.documentElement.lang = locale; persistLocale(locale); });
document.documentElement.lang = normalizeLocale(i18n.language ?? defaultLocale);
export default i18n;
