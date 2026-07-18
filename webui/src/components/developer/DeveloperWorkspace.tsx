import {
  Activity, AppWindow, Bot, Box, ChevronLeft, Clock3, Code2, Database,
  ExternalLink, FileKey2, Gauge, Globe2, KeyRound, PlugZap, RefreshCw,
  Settings2, ShieldCheck, Sparkles, TerminalSquare, Wrench,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ensureAuth } from "@/lib/api";
import type { DeveloperSnapshot } from "@/lib/types";

type DeveloperPage = "overview" | "agents" | "tools" | "models" | "mcp" | "skills" | "automations" | "settings";

const NAV: Array<{ page: DeveloperPage; label: string; icon: typeof Gauge }> = [
  { page: "overview", label: "工作台", icon: Gauge },
  { page: "agents", label: "Agent 与 Worker", icon: Bot },
  { page: "tools", label: "工具", icon: Wrench },
  { page: "models", label: "模型与 Provider", icon: Sparkles },
  { page: "mcp", label: "MCP", icon: PlugZap },
  { page: "skills", label: "Skills", icon: Code2 },
  { page: "automations", label: "Apps 与自动化", icon: Clock3 },
  { page: "settings", label: "运行时设置", icon: Settings2 },
];

function currentPage(): DeveloperPage {
  const value = location.pathname.split("/")[2] as DeveloperPage | undefined;
  return NAV.some((item) => item.page === value) ? value! : "overview";
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="developer-json">{JSON.stringify(value, null, 2)}</pre>;
}

function StatusPill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <span className={`developer-status ${ok ? "ok" : "idle"}`}>{children}</span>;
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return <section className="developer-section"><header><div><h2>{title}</h2>{hint && <p>{hint}</p>}</div></header>{children}</section>;
}

function Overview({ snapshot }: { snapshot: DeveloperSnapshot }) {
  const runtime = snapshot.runtime;
  return <div className="developer-page-grid">
    <section className="developer-hero"><div><span>DEVELOPER CONTROL PLANE</span><h1>后端基础工作台</h1><p>查看 Agent、工具、模型和本地数据边界。学生界面不会显示这些内部信息。</p></div><ShieldCheck size={54} /></section>
    <div className="developer-kpis">
      <article><Activity /><span>Gateway</span><strong>{String(runtime.status ?? "unknown")}</strong></article>
      <article><Bot /><span>活跃 Turn</span><strong>{String(runtime.active_turns ?? 0)}</strong></article>
      <article><Database /><span>持久事件</span><strong>{Number(runtime.durable_events ?? 0).toLocaleString()}</strong></article>
      <article><PlugZap /><span>工具目录版本</span><strong>{snapshot.tools.catalog_revision}</strong></article>
    </div>
    <Section title="能力状态" hint="未配置的通用工作台能力会明确显示，不伪造可用状态。"><div className="developer-card-grid">{Object.entries(snapshot.features).map(([name, feature]) => <article className="developer-card" key={name}><div><AppWindow size={18} /><strong>{name}</strong></div><StatusPill ok={feature.available}>{feature.available ? "已启用" : "未启用"}</StatusPill><p>{feature.reason}</p></article>)}</div></Section>
    <Section title="独立观测平台" hint="Trace、Token、错误和实时事件在隔离端口展示。"><a className="developer-monitor-link" href={`${location.protocol}//${location.hostname}:8766`} target="_blank" rel="noreferrer"><Gauge size={20} /><span><strong>打开 Observability Monitor</strong><small>127.0.0.1:8766</small></span><ExternalLink size={16} /></a></Section>
  </div>;
}

function Agents({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <><Section title="Agent / Worker 运行配置" hint="Coordinator 与 Worker 的迭代、时限、工具结果和兜底策略。"><JsonBlock value={snapshot.agents} /></Section><Section title="当前 Gateway"><JsonBlock value={snapshot.runtime} /></Section></>;
}

function Tools({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <><Section title="工具目录" hint={`${snapshot.tools.items.length} 个已注册工具；权限、风险、超时和重试来自后端真实描述符。`}><div className="developer-table-wrap"><table><thead><tr><th>工具</th><th>来源</th><th>作用域</th><th>风险</th><th>超时</th><th>状态</th></tr></thead><tbody>{snapshot.tools.items.map((tool) => <tr key={String(tool.name)}><td><strong>{String(tool.name)}</strong><small>{String(tool.description ?? "")}</small></td><td>{String(tool.source)} / {String(tool.provider)}</td><td>{Array.isArray(tool.scopes) ? tool.scopes.join(", ") : "-"}</td><td>{String(tool.risk)}</td><td>{String(tool.timeout_s)}s</td><td><StatusPill ok={Boolean(tool.enabled)}>{tool.enabled ? "启用" : "停用"}</StatusPill></td></tr>)}</tbody></table></div></Section><Section title="权限策略"><JsonBlock value={snapshot.tools.policies} /></Section></>;
}

function Models({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <><Section title="Provider / API Key" hint="密钥值永远不会发送到浏览器。"><div className="developer-card-grid">{Object.entries(snapshot.models.providers).map(([name, provider]) => <article className="developer-card" key={name}><div><KeyRound size={18} /><strong>{name}</strong></div><StatusPill ok={Boolean(provider.api_key_configured)}>{provider.api_key_configured ? "密钥已配置" : "缺少密钥"}</StatusPill><p>{String(provider.base_url ?? "")}</p></article>)}</div></Section><Section title="模型路由与故障转移"><JsonBlock value={{ defaults: snapshot.models.defaults, routes: snapshot.models.routes }} /></Section><Section title="思考、生成、超时与重试预设"><JsonBlock value={snapshot.models.presets} /></Section></>;
}

function Mcp({ snapshot }: { snapshot: DeveloperSnapshot }) {
  const entries = Object.entries(snapshot.tools.mcp_servers);
  return <Section title="MCP Servers" hint="连接配置与工具隔离状态；认证头和环境变量只显示是否存在。">{entries.length ? <div className="developer-card-grid">{entries.map(([name, config]) => <article className="developer-card" key={name}><div><PlugZap size={18} /><strong>{name}</strong></div><StatusPill ok>已配置</StatusPill><JsonBlock value={config} /></article>)}</div> : <div className="developer-empty"><PlugZap /><strong>尚未配置 MCP Server</strong><p>在 agent_config.yaml 的 tools.mcp_servers 中添加后会出现在这里。</p></div>}</Section>;
}

function Skills({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <Section title="Skills" hint="统一目录内可被运行时发现的 Markdown/YAML 能力定义。"><div className="developer-list">{snapshot.skills.map((skill) => <article key={skill.path}><FileKey2 size={18} /><span><strong>{skill.name}</strong><small>{skill.path} · {skill.bytes.toLocaleString()} bytes</small></span><StatusPill ok>{skill.format}</StatusPill></article>)}</div></Section>;
}

function Automations({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <><Section title="Apps"><div className="developer-empty"><Box /><strong>Apps Registry 未启用</strong><p>{snapshot.features.apps.reason}</p></div></Section><Section title="Automations / Cron"><div className="developer-empty"><Clock3 /><strong>Cron Runtime 未启用</strong><p>{snapshot.features.automations.reason}</p></div></Section></>;
}

function RuntimeSettings({ snapshot }: { snapshot: DeveloperSnapshot }) {
  return <><Section title="网络与协议"><JsonBlock value={snapshot.web} /></Section><Section title="Workspace 本地数据权限"><div className="developer-list">{snapshot.workspace.roots.map((root) => <article key={root.name}><Database size={18} /><span><strong>{root.name}</strong><small>{root.path}</small></span><StatusPill ok={root.exists}>{root.exists ? "可用" : "未创建"}</StatusPill></article>)}</div></Section><Section title="敏感配置规则" hint="浏览器只能读取脱敏快照。"><div className="developer-callout"><ShieldCheck /><p>Provider 密钥、MCP headers/env、Cookie secret 和 Authorization 字段不会通过开发者 API 返回。配置写入继续由本地 YAML/.env 管理。</p></div></Section></>;
}

export function DeveloperWorkspace() {
  const [page, setPage] = useState<DeveloperPage>(currentPage);
  const [snapshot, setSnapshot] = useState<DeveloperSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { const auth = await ensureAuth(); if (!auth.roles.includes("admin")) throw new Error("当前账户没有开发者权限"); setSnapshot(await api.getDeveloperSnapshot()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => { const listener = () => setPage(currentPage()); addEventListener("popstate", listener); return () => removeEventListener("popstate", listener); }, []);
  const navigate = (next: DeveloperPage) => { history.pushState({}, "", next === "overview" ? "/developer" : `/developer/${next}`); setPage(next); };
  const content = useMemo(() => {
    if (!snapshot) return null;
    if (page === "agents") return <Agents snapshot={snapshot} />;
    if (page === "tools") return <Tools snapshot={snapshot} />;
    if (page === "models") return <Models snapshot={snapshot} />;
    if (page === "mcp") return <Mcp snapshot={snapshot} />;
    if (page === "skills") return <Skills snapshot={snapshot} />;
    if (page === "automations") return <Automations snapshot={snapshot} />;
    if (page === "settings") return <RuntimeSettings snapshot={snapshot} />;
    return <Overview snapshot={snapshot} />;
  }, [page, snapshot]);
  return <div className="developer-shell"><aside className="developer-nav"><div className="developer-brand"><TerminalSquare /><span><strong>NLP Developer</strong><small>Control plane · 8765</small></span></div><nav>{NAV.map(({ page: itemPage, label, icon: Icon }) => <button className={page === itemPage ? "active" : ""} type="button" key={itemPage} onClick={() => navigate(itemPage)}><Icon size={17} />{label}</button>)}</nav><a href="/"><ChevronLeft size={16} />返回学生模式</a></aside><main className="developer-main"><header className="developer-topbar"><div><Globe2 size={16} /><span>本地管理员</span></div><button type="button" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} />刷新</button></header><div className="developer-content">{loading && !snapshot ? <div className="developer-loading"><RefreshCw className="spin" />正在读取运行时…</div> : error ? <div className="developer-error"><ShieldCheck /><strong>无法进入开发者模式</strong><p>{error}</p></div> : content}</div></main></div>;
}
