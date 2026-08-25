import { AlertCircle, BookOpenText, Eye, FileUp, RefreshCw, Save, Send, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/platform/http/api";
import type { TeacherBookArchiveImportPreview, TeacherBookImportPreview, TeacherBookNavigationItem, TeacherBookPage } from "@/shared/types";
import { MarkdownContent } from "@/modules/student/components/MarkdownContent";

type Props = { workspaceId: string };

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return window.btoa(binary);
}

function groupNavigation(items: TeacherBookNavigationItem[]) {
  return items.reduce<Array<{ topicId: string; topicName: string; items: TeacherBookNavigationItem[] }>>((groups, item) => {
    const group = groups.find((value) => value.topicId === item.topic_id);
    if (group) group.items.push(item);
    else groups.push({ topicId: item.topic_id, topicName: item.topic_name, items: [item] });
    return groups;
  }, []);
}

export function TeacherBookEditor({ workspaceId }: Props) {
  const [navigation, setNavigation] = useState<TeacherBookNavigationItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [page, setPage] = useState<TeacherBookPage | null>(null);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState(false);
  const [importPreview, setImportPreview] = useState<TeacherBookImportPreview | null>(null);
  const [importName, setImportName] = useState("");
  const [archivePreview, setArchivePreview] = useState<TeacherBookArchiveImportPreview | null>(null);
  const [archiveName, setArchiveName] = useState("");
  const [archiveBase64, setArchiveBase64] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadNavigation = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api.getTeacherBookNavigation(workspaceId);
      setNavigation(result.items);
      setSelectedId((current) => current || result.items[0]?.knowledge_point_id || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  const loadPage = useCallback(async () => {
    if (!selectedId) {
      setPage(null);
      return;
    }
    setError("");
    try {
      const result = await api.getTeacherBookPage(workspaceId, selectedId);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setImportPreview(null);
      setArchivePreview(null);
      setMessage("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [selectedId, workspaceId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadNavigation(), 0);
    return () => window.clearTimeout(timer);
  }, [loadNavigation]);
  useEffect(() => {
    const timer = window.setTimeout(() => void loadPage(), 0);
    return () => window.clearTimeout(timer);
  }, [loadPage]);

  const groups = useMemo(() => groupNavigation(navigation), [navigation]);
  const save = async () => {
    if (!page || !selectedId) return;
    setSaving(true);
    setMessage("");
    try {
      const result = await api.updateTeacherBookPage(workspaceId, selectedId, content, page.revision);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setMessage("草稿已保存。发布后学生才会看到新内容。");
      await loadNavigation();
    } catch (reason) {
      setMessage(`保存失败：${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (!page || !selectedId) return;
    setSaving(true);
    setMessage("");
    try {
      const draft = content === page.draft_markdown
        ? page
        : (await api.updateTeacherBookPage(workspaceId, selectedId, content, page.revision)).page;
      const result = await api.publishTeacherBookPage(workspaceId, selectedId, draft.revision);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setMessage("教材已发布，学生端现在可以读取这一版正文。");
      await loadNavigation();
    } catch (reason) {
      setMessage(`发布失败：${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setMessage("");
    try {
      const nextPreview = await api.previewTeacherBookImport(workspaceId, file.name, await file.text());
      setImportName(file.name);
      setImportPreview(nextPreview);
    } catch (reason) {
      setMessage(`导入预览失败：${reason instanceof Error ? reason.message : String(reason)}`);
    }
  };

  const handleArchiveFile = async (file: File | undefined) => {
    if (!file) return;
    setMessage("");
    try {
      const archive_base64 = await fileToBase64(file);
      const nextPreview = await api.previewTeacherBookArchiveImport(workspaceId, file.name, archive_base64);
      setArchiveName(file.name);
      setArchiveBase64(archive_base64);
      setArchivePreview(nextPreview);
    } catch (reason) {
      setMessage(`教材包预览失败：${reason instanceof Error ? reason.message : String(reason)}`);
    }
  };

  const applyImport = async () => {
    if (!page || !selectedId || !importPreview) return;
    setSaving(true);
    try {
      const result = await api.applyTeacherBookImport(workspaceId, selectedId, importName, importPreview.content_markdown, page.revision);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setImportPreview(null);
      setMessage("Markdown 已导入草稿，请检查预览后保存或发布。");
      await loadNavigation();
    } catch (reason) {
      setMessage(`导入失败：${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setSaving(false);
    }
  };

  const applyArchive = async () => {
    if (!archivePreview || !archiveBase64) return;
    setSaving(true);
    try {
      const expectedRevisions = Object.fromEntries(
        archivePreview.items.map((item) => [item.knowledge_point_id, item.expected_revision]),
      );
      const result = await api.applyTeacherBookArchiveImport(workspaceId, archiveName, archiveBase64, expectedRevisions);
      setArchivePreview(null);
      setArchiveBase64("");
      setMessage(`教材包已应用 ${result.applied_count} 个知识点草稿${result.asset_paths.length ? `，并保存 ${result.asset_paths.length} 个图片资源` : ""}。请逐页检查后发布。`);
      await loadNavigation();
      await loadPage();
    } catch (reason) {
      setMessage(`教材包应用失败：${reason instanceof Error ? `${reason.message}（请重新预览后再试）` : String(reason)}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading && navigation.length === 0) return <div className="teacher-state"><RefreshCw className="spin" />正在加载教材目录…</div>;
  if (error && navigation.length === 0) return <div className="teacher-state error"><AlertCircle /><strong>无法加载教材内容</strong><p>{error}</p></div>;

  return (
    <div className="teacher-book-editor">
      <section className="teacher-page-summary teacher-book-summary">
        <div><span className="teacher-eyebrow">KNOWLEDGE BOOK</span><h2>知识教材正文</h2><p>长篇 Markdown 正文独立于智能体提示词。教师保存草稿后，再明确发布给学生。</p></div>
        <BookOpenText size={46} />
      </section>
      <div className="teacher-book-toolbar">
        <label className="teacher-book-import"><Upload size={15} />导入 Markdown<input type="file" accept=".md,text/markdown" onChange={(event) => { void handleFile(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
        <label className="teacher-book-import"><Upload size={15} />导入教材包<input type="file" accept=".zip,application/zip" onChange={(event) => { void handleArchiveFile(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
        <button type="button" onClick={() => void loadNavigation()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} />刷新目录</button>
        {message && <span role="status">{message}</span>}
      </div>
      {importPreview && <section className="teacher-book-import-preview" aria-label="Markdown 导入预览"><div><strong>{importName}</strong><span>{importPreview.removed_frameworks.length ? `已过滤：${importPreview.removed_frameworks.join("、")}` : "未发现需要过滤的框架代码"}</span>{importPreview.warnings.map((warning) => <small key={warning}>{warning}</small>)}<details><summary>查看规范化后的 Markdown</summary><pre>{importPreview.content_markdown}</pre></details></div><button type="button" onClick={() => void applyImport()} disabled={saving}><FileUp size={15} />应用到当前草稿</button></section>}
      {archivePreview && <section className="teacher-book-import-preview teacher-book-archive-preview" aria-label="教材包导入预览">
        <div className="teacher-book-archive-summary"><strong>{archivePreview.title}</strong><span>{archiveName} · {archivePreview.items.length} 个待检查知识点 · {archivePreview.asset_paths.length} 个图片资源</span>{archivePreview.warnings.map((warning) => <small key={warning}>{warning}</small>)}</div>
        <div className="teacher-book-archive-items">{archivePreview.items.map((item) => <div className={`teacher-book-archive-item ${item.action}`} key={item.knowledge_point_id}><span className="teacher-book-archive-action">{item.action === "create" ? "新增草稿" : item.action === "update" ? "覆盖草稿" : "内容未变"}</span><strong>{item.title}</strong><small>{item.file_name} · 版本 {item.expected_revision}</small>{item.removed_frameworks.length > 0 && <small>已过滤：{item.removed_frameworks.join("、")}</small>}{item.warnings.map((warning) => <small key={warning}>{warning}</small>)}</div>)}</div>
        {archivePreview.omitted_knowledge_points.length > 0 && <small>未包含的目录知识点不会被删除：{archivePreview.omitted_knowledge_points.length} 个</small>}
        <div className="teacher-book-archive-actions"><button type="button" onClick={() => setArchivePreview(null)} disabled={saving}>取消</button><button type="button" onClick={() => void applyArchive()} disabled={saving || archivePreview.items.every((item) => item.action === "unchanged")}><FileUp size={15} />确认应用到草稿</button></div>
      </section>}
      <div className="teacher-book-layout">
        <aside className="teacher-book-tree" aria-label="教材目录">
          <div className="teacher-book-tree-heading"><strong>教材目录</strong><small>{navigation.length} 个知识点</small></div>
          {groups.map((group) => <section key={group.topicId}><h3>{group.topicName}</h3>{group.items.map((item) => <button key={item.knowledge_point_id} className={selectedId === item.knowledge_point_id ? "active" : ""} type="button" onClick={() => setSelectedId(item.knowledge_point_id)}><span>{item.title}</span>{item.has_published && <small>已发布</small>}</button>)}</section>)}
          {!navigation.length && <p className="teacher-empty-state">请先在“主题与知识点”中创建知识点。</p>}
        </aside>
        <main className="teacher-book-workspace">
          {page ? <>
            <header className="teacher-book-page-heading"><div><span className="teacher-eyebrow">{page.topic_name}</span><h3>{page.title}</h3><small>草稿版本 {page.revision}{page.published_revision != null ? ` · 已发布版本 ${page.published_revision}` : " · 尚未发布"}</small></div><div><button type="button" className={preview ? "active" : ""} onClick={() => setPreview((current) => !current)}><Eye size={15} />{preview ? "返回编辑" : "预览正文"}</button><button type="button" onClick={() => void save()} disabled={saving}><Save size={15} />保存草稿</button><button type="button" className="teacher-book-publish" onClick={() => void publish()} disabled={saving || !content.trim()}><Send size={15} />发布给学生</button></div></header>
            {preview ? <div className="teacher-book-preview"><MarkdownContent>{content || "暂无内容"}</MarkdownContent></div> : <textarea className="teacher-book-textarea" aria-label="教材正文 Markdown" value={content} onChange={(event) => setContent(event.target.value)} placeholder="# 知识点标题\n\n在这里编写面向学生的长篇教材正文。代码块建议使用 ```python，并只保留 PyTorch 示例。" />}
          </> : <div className="teacher-state"><BookOpenText /><p>选择一个知识点开始编写教材。</p></div>}
        </main>
      </div>
    </div>
  );
}
