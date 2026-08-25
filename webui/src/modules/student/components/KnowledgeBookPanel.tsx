import { ChevronDown, ChevronRight, Menu, PanelLeftClose, PanelRightClose, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { api } from "@/platform/http/api";
import type { LearningBookNavigationItem, LearningBookPage } from "@/shared/types";

import { indexMarkdownHeadings } from "./knowledgeBook";
import { MarkdownContent } from "./MarkdownContent";

interface TopicGroup {
  id: string;
  name: string;
  items: LearningBookNavigationItem[];
}

interface BookViewState {
  selectedId: string | null;
  expandedTopics: string[];
  scrollPositions: Record<string, number>;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
}

function readBookViewState(workspaceId: string): BookViewState {
  const fallback: BookViewState = { selectedId: null, expandedTopics: [], scrollPositions: {}, leftCollapsed: false, rightCollapsed: false };
  try {
    const raw = window.sessionStorage.getItem(`nova:knowledge-book:${workspaceId}`);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<BookViewState>;
    return {
      selectedId: typeof parsed.selectedId === "string" ? parsed.selectedId : null,
      expandedTopics: Array.isArray(parsed.expandedTopics) ? parsed.expandedTopics.filter((value): value is string => typeof value === "string") : [],
      scrollPositions: parsed.scrollPositions && typeof parsed.scrollPositions === "object" ? parsed.scrollPositions : {},
      leftCollapsed: parsed.leftCollapsed === true,
      rightCollapsed: parsed.rightCollapsed === true,
    };
  } catch {
    return fallback;
  }
}

function groupNavigation(items: LearningBookNavigationItem[]): TopicGroup[] {
  const groups = new Map<string, TopicGroup>();
  for (const item of items) {
    const group = groups.get(item.topic_id) ?? { id: item.topic_id, name: item.topic_name, items: [] };
    group.items.push(item);
    groups.set(item.topic_id, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: [...group.items].sort((left, right) => left.sort_order - right.sort_order || left.title.localeCompare(right.title, "zh-CN")),
  }));
}

function scrollToHeading(id: string) {
  const element = document.getElementById(id);
  if (!element) return;
  element.scrollIntoView({ behavior: document.documentElement.dataset.reduceMotion === "true" ? "auto" : "smooth", block: "start" });
}

function keepFocusInDrawer(event: ReactKeyboardEvent<HTMLElement>) {
  if (event.key !== "Tab") return;
  const focusable = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not([disabled])")];
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function KnowledgeBookPanel({ workspaceId }: { workspaceId: string }) {
  const [initialViewState] = useState(() => readBookViewState(workspaceId));
  const [navigation, setNavigation] = useState<LearningBookNavigationItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialViewState.selectedId);
  const [page, setPage] = useState<LearningBookPage | null>(null);
  const [loadingNavigation, setLoadingNavigation] = useState(true);
  const [loadingPage, setLoadingPage] = useState(false);
  const [pageReloadToken, setPageReloadToken] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(initialViewState.leftCollapsed);
  const [rightCollapsed, setRightCollapsed] = useState(initialViewState.rightCollapsed);
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(() => new Set(initialViewState.expandedTopics));
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const pageTitleRef = useRef<HTMLHeadingElement>(null);
  const leftDrawerRef = useRef<HTMLElement>(null);
  const rightDrawerRef = useRef<HTMLElement>(null);
  const leftToggleRef = useRef<HTMLButtonElement>(null);
  const rightToggleRef = useRef<HTMLButtonElement>(null);
  const previousLeftOpen = useRef(false);
  const previousRightOpen = useRef(false);
  const scrollPositionsRef = useRef(initialViewState.scrollPositions);
  const scrollPersistTimer = useRef<number | null>(null);
  const topicGroups = useMemo(() => groupNavigation(navigation), [navigation]);
  const visiblePage = page?.knowledge_point_id === selectedId ? page : null;
  const headingIndex = useMemo(() => indexMarkdownHeadings(visiblePage?.content_markdown ?? ""), [visiblePage?.content_markdown]);

  const saveViewState = useCallback(() => {
    try {
      window.sessionStorage.setItem(`nova:knowledge-book:${workspaceId}`, JSON.stringify({
        selectedId,
        expandedTopics: [...expandedTopics],
        scrollPositions: scrollPositionsRef.current,
        leftCollapsed,
        rightCollapsed,
      } satisfies BookViewState));
    } catch {
      // Private browsing and restricted storage should not block reading.
    }
  }, [expandedTopics, leftCollapsed, rightCollapsed, selectedId, workspaceId]);

  const handlePageScroll = () => {
    if (!selectedId || !contentRef.current) return;
    scrollPositionsRef.current[selectedId] = contentRef.current.scrollTop;
    if (scrollPersistTimer.current !== null) window.clearTimeout(scrollPersistTimer.current);
    scrollPersistTimer.current = window.setTimeout(saveViewState, 180);
  };

  useEffect(() => {
    saveViewState();
    return () => {
      if (scrollPersistTimer.current !== null) window.clearTimeout(scrollPersistTimer.current);
      saveViewState();
    };
  }, [saveViewState]);

  const loadNavigation = useCallback(async () => {
    setLoadingNavigation(true);
    setError(null);
    try {
      const response = await api.getLearningBookNavigation(workspaceId);
      setNavigation(response.items);
      setSelectedId((current) => current && response.items.some((item) => item.knowledge_point_id === current) ? current : response.items[0]?.knowledge_point_id ?? null);
      setExpandedTopics((current) => {
        const next = new Set(current);
        if (!next.size && response.items[0]) next.add(response.items[0].topic_id);
        return next;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "教材目录加载失败");
    } finally {
      setLoadingNavigation(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadNavigation(), 0);
    return () => window.clearTimeout(timer);
  }, [loadNavigation]);

  useEffect(() => {
    if (!selectedId) return undefined;
    let current = true;
    const timer = window.setTimeout(() => {
      setLoadingPage(true);
      setError(null);
      void api.getLearningBookPage(workspaceId, selectedId).then((response) => {
        if (!current) return;
        setPage(response.page);
        setActiveHeadingId(null);
      }).catch((cause: unknown) => {
        if (current) setError(cause instanceof Error ? cause.message : "知识点内容加载失败");
      }).finally(() => {
        if (current) setLoadingPage(false);
      });
    }, 0);
    return () => { current = false; window.clearTimeout(timer); };
  }, [pageReloadToken, selectedId, workspaceId]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root || !headingIndex.headings.length || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);
      if (visible[0]) setActiveHeadingId(visible[0].target.id);
    }, { root, rootMargin: "-8% 0px -72% 0px", threshold: [0, 1] });
    for (const heading of headingIndex.headings) {
      const element = document.getElementById(heading.id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [headingIndex, visiblePage?.knowledge_point_id]);

  useEffect(() => {
    if (!visiblePage || loadingPage) return undefined;
    const timer = window.setTimeout(() => {
      const root = contentRef.current;
      const savedScrollTop = scrollPositionsRef.current[visiblePage.knowledge_point_id] ?? 0;
      if (root && savedScrollTop > 0) root.scrollTo?.({ top: savedScrollTop, behavior: "auto" });
      pageTitleRef.current?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadingPage, visiblePage]);

  useEffect(() => {
    if (!leftOpen && !rightOpen) return undefined;
    const closeDrawers = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setLeftOpen(false);
      setRightOpen(false);
    };
    window.addEventListener("keydown", closeDrawers);
    return () => window.removeEventListener("keydown", closeDrawers);
  }, [leftOpen, rightOpen]);

  useEffect(() => {
    const wasOpen = previousLeftOpen.current;
    previousLeftOpen.current = leftOpen;
    const timer = window.setTimeout(() => {
      if (leftOpen) leftDrawerRef.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
      else if (wasOpen) leftToggleRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [leftOpen]);

  useEffect(() => {
    const wasOpen = previousRightOpen.current;
    previousRightOpen.current = rightOpen;
    const timer = window.setTimeout(() => {
      if (rightOpen) rightDrawerRef.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
      else if (wasOpen) rightToggleRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [rightOpen]);

  const selectedIndex = navigation.findIndex((item) => item.knowledge_point_id === selectedId);
  const selectKnowledgePoint = (id: string) => {
    setSelectedId(id);
    setLeftOpen(false);
    setRightOpen(false);
  };

  return <section className="knowledge-book-panel" aria-label="知识教材">
    <header className="knowledge-book-toolbar">
      <div className="knowledge-book-brand"><Menu size={16} /><strong>知识教材</strong><span>{visiblePage?.topic_name ?? "教师发布的实操内容"}</span></div>
      <div className="knowledge-book-toolbar-actions">
        <button ref={leftToggleRef} type="button" className="knowledge-book-outline-toggle left" aria-label="打开教材目录" aria-expanded={leftOpen} onClick={() => setLeftOpen((value) => !value)}>{leftOpen ? <PanelLeftClose size={15} /> : <Menu size={15} />}<span>大纲</span></button>
        <button ref={rightToggleRef} type="button" className="knowledge-book-outline-toggle right" aria-label="打开本页目录" aria-expanded={rightOpen} onClick={() => setRightOpen((value) => !value)}>{rightOpen ? <PanelRightClose size={15} /> : <PanelRightClose size={15} />}<span>本页</span></button>
        <button type="button" className="knowledge-book-refresh" aria-label="刷新教材目录" onClick={() => void loadNavigation()} disabled={loadingNavigation}><RefreshCw size={15} className={loadingNavigation ? "spin" : undefined} /></button>
      </div>
    </header>
    <div className={["knowledge-book-layout", leftCollapsed && "left-collapsed", rightCollapsed && "right-collapsed"].filter(Boolean).join(" ")}>
      <aside ref={leftDrawerRef} onKeyDown={keepFocusInDrawer} className={["knowledge-book-sidebar", leftOpen && "drawer-open", leftCollapsed && "collapsed"].filter(Boolean).join(" ")} aria-label="教材大纲">
        <button type="button" className="knowledge-book-collapsed-toggle" aria-label="展开教材目录" onClick={() => setLeftCollapsed(false)}><PanelLeftClose size={16} /></button>
        <div className="knowledge-book-sidebar-heading"><strong>课程目录</strong><button type="button" aria-label="收起教材目录" onClick={() => { setLeftOpen(false); setLeftCollapsed(true); }}><X size={15} /></button></div>
        {loadingNavigation ? <p className="knowledge-book-muted">正在加载目录……</p> : topicGroups.length ? topicGroups.map((group) => {
          const expanded = expandedTopics.has(group.id);
          return <section className="knowledge-book-topic" key={group.id}>
            <button type="button" className="knowledge-book-topic-heading" aria-expanded={expanded} onClick={() => setExpandedTopics((current) => { const next = new Set(current); if (next.has(group.id)) next.delete(group.id); else next.add(group.id); return next; })}><span>{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<strong>{group.name}</strong></span><small>{group.items.length}</small></button>
            {expanded && <div className="knowledge-book-topic-items">{group.items.map((item) => <button type="button" key={item.knowledge_point_id} className={item.knowledge_point_id === selectedId ? "active" : ""} onClick={() => selectKnowledgePoint(item.knowledge_point_id)}><span>{item.title}</span></button>)}</div>}
          </section>;
        }) : <p className="knowledge-book-muted">教师还没有发布知识教材。</p>}
      </aside>
      <main className="knowledge-book-main">
        {error && <div className="knowledge-book-error" role="alert"><span>{error}</span><button type="button" onClick={() => selectedId ? setPageReloadToken((value) => value + 1) : void loadNavigation()}>重试</button></div>}
        <div className="knowledge-book-page-scroll" ref={contentRef} onScroll={handlePageScroll}>
          {loadingPage ? <div className="knowledge-book-state"><span className="spin">⟳</span><p>正在打开知识点……</p></div> : visiblePage ? <article className="knowledge-book-article">
            <header><p>{visiblePage.topic_name}</p><h1 ref={pageTitleRef} tabIndex={-1}>{visiblePage.title}</h1><small>教师教材 · 第 {selectedIndex + 1} 节</small></header>
            <MarkdownContent headingIds={headingIndex.headingIds}>{visiblePage.content_markdown}</MarkdownContent>
            <footer className="knowledge-book-page-nav">
              <button type="button" disabled={selectedIndex <= 0} onClick={() => selectKnowledgePoint(navigation[selectedIndex - 1].knowledge_point_id)}>上一节</button>
              <button type="button" disabled={selectedIndex < 0 || selectedIndex >= navigation.length - 1} onClick={() => selectKnowledgePoint(navigation[selectedIndex + 1].knowledge_point_id)}>下一节</button>
            </footer>
          </article> : <div className="knowledge-book-state"><Menu size={26} /><p>{loadingNavigation ? "正在加载教材……" : "从左侧目录选择一个知识点开始阅读。"}</p></div>}
        </div>
      </main>
      <aside ref={rightDrawerRef} onKeyDown={keepFocusInDrawer} className={["knowledge-book-toc", rightOpen && "drawer-open", rightCollapsed && "collapsed"].filter(Boolean).join(" ")} aria-label="本页目录">
        <button type="button" className="knowledge-book-collapsed-toggle" aria-label="展开本页目录" onClick={() => setRightCollapsed(false)}><PanelRightClose size={16} /></button>
        <div className="knowledge-book-sidebar-heading"><strong>本页目录</strong><button type="button" aria-label="收起本页目录" onClick={() => { setRightOpen(false); setRightCollapsed(true); }}><X size={15} /></button></div>
        {headingIndex.headings.length ? <nav>{headingIndex.headings.map((heading) => <button type="button" key={heading.id} className={activeHeadingId === heading.id ? "active" : ""} style={{ paddingLeft: `${12 + (heading.level - 2) * 12}px` }} onClick={() => scrollToHeading(heading.id)}>{heading.text}</button>)}</nav> : <p className="knowledge-book-muted">本页暂无小标题。</p>}
      </aside>
    </div>
  </section>;
}
