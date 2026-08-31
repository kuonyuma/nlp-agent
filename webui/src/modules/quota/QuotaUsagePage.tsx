import { Activity, BarChart3, CheckCircle2, CircleAlert, Clock3, Coins, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useOptionalAuth } from "@/platform/auth/AuthContext";
import { api, ApiError } from "@/platform/http/api";
import { StudentSocket } from "@/platform/realtime/client";
import type { QuotaBucketSnapshot, QuotaPolicyExplanation, QuotaSnapshot, QuotaUsageBreakdown, QuotaUsageSnapshot } from "@/shared/types";

export const formatMicro = (value: number | null | undefined) => `${Number(value ?? 0).toLocaleString("zh-CN")} μcredits`;
const formatLimit = (value: number | null) => value == null ? "无限" : formatMicro(value);
const ownerLabel = (ownerType: QuotaBucketSnapshot["owner_type"]) => ownerType === "workspace" ? "工作空间" : ownerType === "classroom" ? "课堂" : "用户";

function BucketCard({ bucket }: { bucket: QuotaBucketSnapshot }) {
  const capacity = (bucket.limit_micro ?? 0) + bucket.grant_micro + bucket.adjustment_micro;
  const used = bucket.consumed_micro + bucket.reserved_micro;
  const progress = capacity > 0 ? Math.min(100, Math.max(0, used / capacity * 100)) : 0;
  return <article className={`quota-bucket-card${bucket.over_limit ? " is-over-limit" : ""}`}>
    <div className="quota-bucket-heading"><span>{ownerLabel(bucket.owner_type)} · {bucket.bucket_type === "daily" ? "今日" : "本月"}</span><strong>{formatMicro(bucket.remaining_micro)}</strong></div>
    <div className="quota-progress" aria-label="额度使用进度"><i style={{ width: `${progress}%` }} /></div>
    <dl><div><dt>策略上限</dt><dd>{formatLimit(bucket.limit_micro)}</dd></div><div><dt>已消耗</dt><dd>{formatMicro(bucket.consumed_micro)}</dd></div><div><dt>预占中</dt><dd>{formatMicro(bucket.reserved_micro)}</dd></div><div><dt>Grant / 调整</dt><dd>{formatMicro(bucket.grant_micro + bucket.adjustment_micro)}</dd></div></dl>
    <small>重置时间：{new Date(bucket.reset_at).toLocaleString("zh-CN")}</small>
    {bucket.over_limit && <p className="quota-warning"><CircleAlert size={14} />实际用量已超过额度，后续请求将被拦截。</p>}
  </article>;
}

function PolicyExplanation({ policy }: { policy: QuotaPolicyExplanation | null }) {
  if (!policy) return <div className="quota-empty"><ShieldCheck size={20} /><span>当前还没有可解释的基础策略，请联系开发者配置。</span></div>;
  return <div className="quota-policy-explanation"><div><strong>基础策略</strong><span>{policy.base.code} · v{policy.base.version}</span><small>来源：{policy.base.reason.subject_type} / {policy.base.reason.subject_id}，优先级 {policy.base.reason.priority}</small></div>{policy.workspace && <div><strong>工作空间预算</strong><span>{policy.workspace.code} · v{policy.workspace.version}</span><small>来源：workspace / {policy.workspace.reason.subject_id}</small></div>}</div>;
}

function UsageTrend({ breakdown }: { breakdown: QuotaUsageBreakdown[] }) {
  const days = useMemo(() => {
    const grouped = new Map<string, number>();
    breakdown.forEach((item) => grouped.set(item.day, (grouped.get(item.day) ?? 0) + item.priced_credits_micro));
    const values = [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-14);
    const max = Math.max(1, ...values.map(([, value]) => value));
    return values.map(([day, value]) => ({ day, value, height: Math.max(5, value / max * 100) }));
  }, [breakdown]);
  return <section className="quota-panel quota-trend-panel"><div className="quota-panel-heading"><div><h2>用量趋势</h2><p>按天汇总已计价 Credits；待对账事件不会被伪装成 0。</p></div><BarChart3 size={19} /></div>{days.length ? <div className="quota-trend-chart" aria-label="近 14 天用量趋势">{days.map((item) => <div className="quota-trend-column" key={item.day} title={`${item.day} · ${formatMicro(item.value)}`}><i style={{ height: `${item.height}%` }} /><small>{item.day.slice(5)}</small></div>)}</div> : <div className="quota-empty quota-empty-compact"><BarChart3 size={18} /><span>当前周期还没有可绘制的用量。</span></div>}</section>;
}

function UsageBreakdown({ usage }: { usage: QuotaUsageSnapshot | null }) {
  const breakdown = usage?.breakdown ?? [];
  return <section className="quota-panel"><div className="quota-panel-heading"><div><h2>调用明细</h2><p>按日期、用途、Provider 和模型聚合；数据只读，不改变额度流水。</p></div><span className={`quota-data-status ${usage?.credits_complete ? "complete" : "partial"}`}>{usage?.credits_complete ? "已完整计价" : "部分待处理"}</span></div>{breakdown.length ? <div className="quota-breakdown-list">{breakdown.slice().reverse().slice(0, 12).map((item) => <article className="quota-breakdown-row" key={`${item.day}-${item.purpose}-${item.provider}-${item.provider_model}`}><div><strong>{item.purpose} · {item.provider} / {item.provider_model}</strong><small>{item.day} · {item.events} 次调用 · {item.total_tokens.toLocaleString("zh-CN")} tokens</small></div><div className="quota-breakdown-value"><strong>{formatMicro(item.priced_credits_micro)}</strong><small>{item.unpriced_events ? `待处理 ${item.unpriced_events} 条` : `${item.priced_events} 条已计价`}</small></div></article>)}</div> : <div className="quota-empty"><Activity size={20} /><span>近 {usage?.period_days ?? 30} 天暂无模型调用记录。</span></div>}</section>;
}

export function QuotaUsagePage({ embedded = false, userId, workspaceIds: providedWorkspaceIds }: { embedded?: boolean; userId?: string; workspaceIds?: string[] }) {
  const auth = useOptionalAuth();
  const authUser = auth?.user;
  const resolvedUserId = userId ?? authUser?.user_id;
  const workspaceIds = useMemo(() => (providedWorkspaceIds ?? authUser?.workspace_ids ?? []).filter((item) => item !== "*"), [authUser, providedWorkspaceIds]);
  const hasAuthContext = Boolean(authUser || userId || providedWorkspaceIds);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>();
  const selectedWorkspaceId = workspaceId && workspaceIds.includes(workspaceId) ? workspaceId : workspaceIds[0];
  const [quota, setQuota] = useState<QuotaSnapshot | null>(null);
  const [policy, setPolicy] = useState<QuotaPolicyExplanation | null>(null);
  const [usage, setUsage] = useState<QuotaUsageSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!hasAuthContext || !resolvedUserId || (workspaceIds.length > 0 && !selectedWorkspaceId)) return;
    setError("");
    try {
      const [quotaResult, usageResult] = await Promise.all([api.getQuota(selectedWorkspaceId), api.getUsage(30, selectedWorkspaceId)]);
      setQuota(quotaResult.quota);
      setPolicy(quotaResult.policy);
      setUsage(usageResult);
    } catch (reason) {
      setError(reason instanceof ApiError && reason.status === 403
        ? "当前账号没有该工作空间的额度查看权限，请切换到已加入的工作空间。"
        : reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [hasAuthContext, resolvedUserId, selectedWorkspaceId, workspaceIds]);
  useEffect(() => {
    if (!hasAuthContext) {
      queueMicrotask(() => setLoading(false));
      return;
    }
    queueMicrotask(() => void load());
  }, [hasAuthContext, load]);
  useEffect(() => {
    if (!hasAuthContext) return undefined;
    const socket = new StudentSocket((event) => {
      if (event.type === "usage.snapshot") void load();
    }, () => undefined);
    socket.connect();
    return () => socket.close();
  }, [hasAuthContext, load]);
  const buckets = useMemo(() => quota?.buckets ?? [], [quota]);
  const effectiveRemaining = buckets.length > 0 ? Math.min(...buckets.map((item) => item.remaining_micro)) : null;
  const totalTokens = usage?.tokens?.total_tokens ?? 0;
  if (loading && !quota) return <main className={`quota-page${embedded ? " quota-page-embedded" : ""}`}><div className="quota-loading"><RefreshCw className="spin" />正在读取额度快照…</div></main>;
  return <main className={`quota-page${embedded ? " quota-page-embedded" : ""}`}>
    <header className="quota-page-header"><div><span className="quota-eyebrow">ACCOUNT RESOURCE</span><h1>额度与用量</h1><p>额度由开发者统一分配。当前可用值取所有有效 Bucket 的最小值，和 Codex 一样只展示真正可发起请求的额度。</p></div><div className="quota-header-actions">{workspaceIds.length > 0 && <label className="quota-workspace-selector" htmlFor="quota-workspace"><span>工作空间</span><select id="quota-workspace" value={selectedWorkspaceId ?? ""} onChange={(event) => setWorkspaceId(event.target.value || undefined)}>{workspaceIds.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>}<button type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} />刷新快照</button></div></header>
    {error && <div className="quota-error" role="alert"><CircleAlert size={17} /><span>{error}</span><button type="button" onClick={() => void load()}>重试</button></div>}
    <section className="quota-summary-grid quota-summary-grid-four"><article className="quota-summary-primary"><Coins /><span>当前可用</span><strong>{effectiveRemaining == null ? "暂无额度" : formatMicro(effectiveRemaining)}</strong><small>受用户、工作空间和周期限制共同约束</small></article><article><Activity /><span>30 天已计费用量</span><strong>{formatMicro(usage?.priced_credits_micro)}</strong><small>{usage?.unpriced_events ? `另有 ${usage.unpriced_events} 条待处理` : "所有已记录事件均已计价"}</small></article><article><BarChart3 /><span>累计 Token</span><strong>{totalTokens.toLocaleString("zh-CN")}</strong><small>输入、输出及推理 Token 合计</small></article><article><Clock3 /><span>账务状态</span><strong>{usage?.credits_complete ? "完整" : "待补齐"}</strong><small>{Number(usage?.events ?? 0).toLocaleString("zh-CN")} 条 UsageEvent</small></article></section>
    <section className="quota-panel"><div className="quota-panel-heading"><div><h2>当前额度</h2><p>预占中的额度不会重复分配；有效 Grant、手工调整和有限透支已反映在每个 Bucket 中。</p></div>{usage?.workspace_id && <span className="quota-scope-pill">workspace / {usage.workspace_id}</span>}</div><div className="quota-bucket-grid">{buckets.map((bucket) => <BucketCard bucket={bucket} key={`${bucket.owner_type}-${bucket.owner_id}-${bucket.bucket_type}`} />)}{buckets.length === 0 && <div className="quota-empty"><Coins size={20} /><span>当前周期还没有生成额度 Bucket。</span></div>}</div></section>
    <UsageTrend breakdown={usage?.breakdown ?? []} />
    <UsageBreakdown usage={usage} />
    <section className="quota-panel"><div className="quota-panel-heading"><div><h2>策略来源</h2><p>多角色不会叠加额度，服务端会选择一个可解释的基础策略。</p></div><CheckCircle2 size={19} /></div><PolicyExplanation policy={policy} /></section>
  </main>;
}

export default QuotaUsagePage;
