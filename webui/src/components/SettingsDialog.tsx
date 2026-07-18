import { Moon, Sun, X } from "lucide-react";

import type { UserSettings } from "@/lib/types";

export function SettingsDialog({ open, settings, onClose, onChange }: {
  open: boolean;
  settings: UserSettings;
  onClose: () => void;
  onChange: (patch: Partial<UserSettings>) => void;
}) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-label="偏好设置" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><strong>学生偏好设置</strong><p>只显示与学习体验相关的选项</p></div><button className="icon-button" type="button" onClick={onClose}><X size={18} /></button></header>
        <div className="setting-row"><div><strong>界面主题</strong><p>跟随系统或手动选择</p></div><div className="segmented"><button className={settings.theme === "light" ? "active" : ""} onClick={() => onChange({ theme: "light" })}><Sun size={14} />浅色</button><button className={settings.theme === "dark" ? "active" : ""} onClick={() => onChange({ theme: "dark" })}><Moon size={14} />深色</button><button className={settings.theme === "system" ? "active" : ""} onClick={() => onChange({ theme: "system" })}>自动</button></div></div>
        <label className="setting-row"><div><strong>界面语言</strong><p>语言偏好会同步到后端设置</p></div><select value={settings.locale} onChange={(event) => onChange({ locale: event.target.value })}><option value="zh-CN">简体中文</option><option value="en">English</option></select></label>
        <label className="setting-row"><div><strong>显示思考内容</strong><p>默认仅展示教育化处理状态</p></div><input type="checkbox" checked={settings.show_reasoning} onChange={(event) => onChange({ show_reasoning: event.target.checked })} /></label>
      </section>
    </div>
  );
}
