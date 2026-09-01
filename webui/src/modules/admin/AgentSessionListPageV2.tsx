import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/platform/http/api";
import type { AgentSessionStats, SessionSummary } from "@/shared/types";

const PAGE_SIZE = 24;

function formatDate(value: string | number | undefined | null) {
  if (value == null) return "-";
  const date = new Date(typeof value === "number" && value < 1_000_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN");
}

function sessionTitle(item: SessionSummary) {
  return item.title?.trim() || "未命名会话";
}

function shortId(value: string) {
  return value.length > 18 ? `${value.slice(0, 14)}…` : value;
}

export function AgentSessionListPageV2() {
  const [items, setItems] = useState<SessionSummary[]>([]);
  const [stats, setStats] = useState<AgentSessionStats | null>(null);
  const [selected, setSelected] = useState<SessionSummary | null>(null);
  const [turns, setTurns] = useState<Awaited<ReturnType<typeof api.listTurns>>["items"]>([]);
  const [message, setMessage] = useState("");
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [managedId, setManagedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const itemsRef = useRef<SessionSummary[]>([]);
  const nextOffsetRef = useRef(0);

  const load = useCallback(async (append = false) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      const currentLength = itemsRef.current.length;
      const requestOffset = append ? nextOffsetRef.current : 0;
      const page = await api.listSessions({ limit: PAGE_SIZE, offset: requestOffset });
      const nextLength = append ? currentLength + page.items.length : page.items.length;
      nextOffsetRef.current = (page.offset ?? requestOffset) + (page.limit ?? PAGE_SIZE);
      setItems((current) => {
        const next = append ? [...current, ...page.items] : page.items;
        itemsRef.current = next;
        return next;
      });
      setTotal(page.total ?? page.items.length);
      setHasMore(page.has_more ?? (page.total ?? 0) > nextLength);
      if (!append) setStats(await api.getSessionStats());
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, []);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const select = async (item: SessionSummary) => {
    setSelected(item);
    setManagedId(null);
    setEditingId(null);
    try {
      setTurns((await api.listTurns(item.session_id)).items);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载会话记录失败");
    }
  };

  const remove = async (item: SessionSummary) => {
    if (!confirm(`删除 Agent 会话「${sessionTitle(item)}」？`)) return;
    try {
      await api.deleteSession(item.session_id);
      setSelected((current) => current?.session_id === item.session_id ? null : current);
      setManagedId(null);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  };

  const startRename = (item: SessionSummary) => {
    setManagedId(item.session_id);
    setEditingId(item.session_id);
    setEditingTitle(sessionTitle(item));
  };

  const rename = async (item: SessionSummary) => {
    const nextTitle = editingTitle.trim();
    if (!nextTitle) {
      setMessage("会话名称不能为空");
      return;
    }
    try {
      await api.renameSession(item.session_id, nextTitle);
      const update = (current: SessionSummary) => current.session_id === item.session_id ? { ...current, title: nextTitle, title_is_manual: true } : current;
      setItems((current) => current.map(update));
      setSelected((current) => current && update(current));
      setEditingId(null);
      setManagedId(null);
      setMessage("会话名称已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "修改名称失败");
    }
  };

  const detailSession = selected ?? items[0] ?? null;
  const rangeLabel = useMemo(() => total ? `已加载 ${items.length} / ${total}` : "0 条", [items.length, total]);

  return (
    <div className="developer-sessions-page">
      <div className="developer-page-heading">
        <div>
          <span className="developer-eyebrow">AGENT OPERATIONS · ON DEMAND</span>
          <h1>Agent 会话</h1>
          <p>会话是一次 Agent 工作上下文的容器，用于回看 Agent 的请求、Turn 状态和运行上下文。列表只加载当前批次，需要时再继续加载。</p>
        </div>
        <span className="developer-page-badge">按需加载 · {PAGE_SIZE} 条 / 批</span>
      </div>

      {stats && <div className="developer-session-stats">{[["会话总数", stats.sessions_total, "全部上下文"], ["活跃会话", stats.sessions_active, "仍有请求活动"], ["Turn 总数", stats.turns_total ?? "-", "可回看执行单元"], ["近 24 小时 Turn", stats.turns_last_24h ?? "-", "最近一天"]].map(([label, value, hint]) => <article key={String(label)}><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>)}</div>}

      {message && <div className="developer-form-message developer-sessions-message" role="status">{message}</div>}
      <div className="developer-sessions-layout">
        <section className="developer-section developer-session-list-panel">
          <header><div><h2>会话目录</h2><p>{rangeLabel} · 标题优先，ID 仅用于定位</p></div><span className="developer-section-kicker">SESSION INDEX</span></header>
          <div className="developer-session-list">
            {loading && <div className="developer-session-empty">正在读取会话目录…</div>}
            {!loading && items.map((item) => {
              const title = sessionTitle(item);
              const isManaged = managedId === item.session_id;
              const isEditing = editingId === item.session_id;
              return <article className={`developer-session-card ${selected?.session_id === item.session_id ? "selected" : ""}`} key={item.session_id}>
                <button className="developer-session-select" type="button" aria-label={`查看会话 ${title}`} onClick={() => void select(item)}>
                  <span className="developer-session-icon">AG</span><span className="developer-session-copy"><strong>{title}</strong><small>Session ID · {shortId(item.session_id)}</small><small>{item.channel} · {formatDate(item.last_active ?? item.created_at)}</small></span>
                </button>
                <button className={`developer-session-manage ${isManaged ? "active" : ""}`} type="button" aria-label={`管理会话 ${title}`} onClick={() => setManagedId(isManaged ? null : item.session_id)}>管理</button>
                {isManaged && <div className="developer-session-actions">{isEditing ? <><label><span>会话名称</span><input aria-label="会话名称" value={editingTitle} onChange={(event) => setEditingTitle(event.target.value)} /></label><button type="button" onClick={() => void rename(item)}>保存名称</button><button className="secondary" type="button" onClick={() => setEditingId(null)}>取消</button></> : <><button type="button" onClick={() => startRename(item)}>修改名称</button><button className="danger" type="button" onClick={() => void remove(item)}>删除会话</button></>}</div>}
              </article>;
            })}
            {!loading && !items.length && <div className="developer-session-empty">暂无 Agent 会话</div>}
          </div>
          {!loading && <div className="developer-session-more"><span>{hasMore ? "还有更多会话，按需加载" : "已加载全部会话"}</span>{hasMore && <button type="button" onClick={() => void load(true)} disabled={loadingMore}>{loadingMore ? "正在加载…" : "加载更多会话"}</button>}</div>}
        </section>

        <section className="developer-section developer-session-detail">
          <header><div><span className="developer-section-kicker">SESSION CONTEXT</span><h2>{detailSession ? sessionTitle(detailSession) : "选择一个会话"}</h2><p>{detailSession ? `所有者 ${detailSession.user_id} · 工作区 ${detailSession.workspace_id}` : "选择会话后才会读取 Turn 详情"}</p></div></header>
          {detailSession ? <div className="developer-session-detail-body"><div className="developer-session-purpose"><strong>这个会话有什么用？</strong><p>用于回看 Agent 的请求、Turn 状态和运行上下文。选择左侧会话后，系统才会读取它的 Turn 元数据。</p><code>{detailSession.session_id}</code></div><div className="developer-turn-list">{selected ? turns.map((turn) => <article key={turn.turn_id}><div><strong>{turn.turn_id}</strong><span>{turn.status}</span></div><small>创建：{formatDate(turn.created_at)} · {turn.completed_at ? `完成：${formatDate(turn.completed_at)}` : "仍在处理或未完成"}</small></article>) : <p className="developer-session-hint">选择左侧会话查看 Turn 元数据</p>}{selected && !turns.length && <p className="developer-session-hint">暂无 Turn</p>}</div></div> : <p className="developer-session-hint">当前还没有可查看的会话。</p>}
        </section>
      </div>
    </div>
  );
}
