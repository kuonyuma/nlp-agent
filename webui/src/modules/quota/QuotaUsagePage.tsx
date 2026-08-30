import { Activity, CircleAlert, Clock3, Coins, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/platform/auth/AuthContext";
import { api } from "@/platform/http/api";
import { StudentSocket } from "@/platform/realtime/client";
import type { QuotaBucketSnapshot, QuotaPolicyExplanation, QuotaSnapshot } from "@/shared/types";

type UsageView = {
  events?: number;
  priced_credits_micro?: number;
  credits_micro?: number | null;
  credit_status?: string;
  tokens?: Record<string, number>;
};

const formatMicro = (value: number | null | undefined) => `${Number(value ?? 0).toLocaleString("zh-CN")} μcredits`;
const formatLimit = (value: number | null) => value == null ? "无限" : formatMicro(value);

function BucketCard({ bucket }: { bucket: QuotaBucketSnapshot }) {
  const capacity = (bucket.limit_micro ?? 0) + bucket.grant_micro + bucket.adjustment_micro;
  const used = bucket.consumed_micro + bucket.reserved_micro;
  const progress = capacity > 0 ? Math.min(100, Math.max(0, used / capacity * 100)) : 0;
  const ownerLabel = bucket.owner_type === "workspace" ? "工作空间" : bucket.owner_type === "classroom" ? "课堂" : "用户";
  return <article className="quota-bucket-card">
    <div className="quota-bucket-heading"><span>{ownerLabel} · {bucket.bucket_type === "daily" ? "今日" : "本月"}</span><strong>{formatMicro(bucket.remaining_micro)}</strong></div>
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

export function QuotaUsagePage() {
  const { user } = useAuth();
  const workspaceIds = useMemo(() => user?.workspace_ids.filter((item) => item !== "*") ?? [], [user]);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>();
  const selectedWorkspaceId = workspaceId && workspaceIds.includes(workspaceId) ? workspaceId : workspaceIds[0];
  const [quota, setQuota] = useState<QuotaSnapshot | null>(null);
  const [policy, setPolicy] = useState<QuotaPolicyExplanation | null>(null);
  const [usage, setUsage] = useState<UsageView | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!user || (workspaceIds.length > 0 && !selectedWorkspaceId)) return;
    setError("");
    try {
      const [quotaResult, usageResult] = await Promise.all([api.getQuota(selectedWorkspaceId), api.getUsage(30)]);
      setQuota(quotaResult.quota);
      setPolicy(quotaResult.policy);
      setUsage(usageResult as UsageView);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [user, selectedWorkspaceId, workspaceIds]);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => {
    const socket = new StudentSocket((event) => {
      if (event.type === "usage.snapshot") void load();
    }, () => undefined);
    socket.connect();
    return () => socket.close();
  }, [load]);
  const buckets = useMemo(() => quota?.buckets ?? [], [quota]);
  const effectiveRemaining = buckets.length > 0 ? Math.min(...buckets.map((item) => item.remaining_micro)) : null;
  if (loading && !quota) return <main className="quota-page"><div className="quota-loading"><RefreshCw className="spin" />正在读取额度快照…</div></main>;
  return <main className="quota-page">
    <header className="quota-page-header"><div><span className="quota-eyebrow">ACCOUNT RESOURCE</span><h1>额度与用量</h1><p>额度由开发者统一分配。页面只展示当前账号可用的额度、预占和真实消耗。</p></div><div className="quota-header-actions">{workspaceIds.length > 1 && <label className="quota-workspace-selector" htmlFor="quota-workspace"><span>工作空间</span><select id="quota-workspace" value={selectedWorkspaceId ?? ""} onChange={(event) => setWorkspaceId(event.target.value || undefined)}>{workspaceIds.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>}<button type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "spin" : ""} />刷新快照</button></div></header>
    {error && <div className="quota-error" role="alert"><CircleAlert size={17} /><span>{error}</span><button type="button" onClick={() => void load()}>重试</button></div>}
    <section className="quota-summary-grid"><article><Coins /><span>当前可用</span><strong>{effectiveRemaining == null ? "暂无额度" : formatMicro(effectiveRemaining)}</strong></article><article><Activity /><span>30 天已计费用量</span><strong>{formatMicro(usage?.priced_credits_micro)}</strong></article><article><Clock3 /><span>已记录事件</span><strong>{Number(usage?.events ?? 0).toLocaleString("zh-CN")}</strong></article></section>
    <section className="quota-panel"><div className="quota-panel-heading"><div><h2>当前额度 Bucket</h2><p>用户策略与工作空间预算同时生效；预占中的额度不会重复分配。</p></div></div><div className="quota-bucket-grid">{buckets.map((bucket) => <BucketCard bucket={bucket} key={`${bucket.owner_type}-${bucket.owner_id}-${bucket.bucket_type}`} />)}{buckets.length === 0 && <div className="quota-empty"><Coins size={20} /><span>当前周期还没有生成额度 Bucket。</span></div>}</div></section>
    <section className="quota-panel"><div className="quota-panel-heading"><div><h2>策略来源</h2><p>多角色不会叠加额度，服务端会选择一个可解释的基础策略。</p></div></div><PolicyExplanation policy={policy} /></section>
  </main>;
}

export default QuotaUsagePage;
