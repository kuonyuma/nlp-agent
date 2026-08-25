import { AlertCircle, BookOpenText, Eye, FileUp, RefreshCw, Save, Send, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/platform/http/api";
import type { TeacherBookArchiveImportPreview, TeacherBookAssetInput, TeacherBookImportPreview, TeacherBookNavigationItem, TeacherBookPage } from "@/shared/types";
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

function assetPathForFile(file: File): string {
  const relativePath = file.webkitRelativePath.replaceAll("\\", "/");
  const assetsIndex = relativePath.indexOf("assets/");
  return assetsIndex >= 0 ? relativePath.slice(assetsIndex) : `assets/${file.name}`;
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
  const [importAssets, setImportAssets] = useState<TeacherBookAssetInput[]>([]);
  const [editorAssets, setEditorAssets] = useState<TeacherBookAssetInput[]>([]);
  const [archivePreview, setArchivePreview] = useState<TeacherBookArchiveImportPreview | null>(null);
  const [archiveName, setArchiveName] = useState("");
  const [archiveBase64, setArchiveBase64] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const pageRequestId = useRef(0);

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
    const requestId = ++pageRequestId.current;
    const requestedId = selectedId;
    if (!requestedId) {
      setPage(null);
      return;
    }
    setError("");
    try {
      const result = await api.getTeacherBookPage(workspaceId, requestedId);
      if (requestId !== pageRequestId.current) return;
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setImportPreview(null);
      setImportAssets([]);
      setEditorAssets([]);
      setArchivePreview(null);
      setMessage("");
    } catch (reason) {
      if (requestId !== pageRequestId.current) return;
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
      const result = await api.updateTeacherBookPage(workspaceId, selectedId, content, page.revision, editorAssets);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setEditorAssets([]);
      const warningMessage = result.warnings.length > 0 ? `提示：${result.warnings.join("；")}` : "";
      setMessage(`草稿已保存。发布后学生才会看到新内容。${warningMessage ? ` ${warningMessage}` : ""}`);
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
      let draft = page;
      let warnings: string[] = [];
      if (content !== page.draft_markdown || editorAssets.length > 0) {
        const saved = await api.updateTeacherBookPage(workspaceId, selectedId, content, page.revision, editorAssets);
        draft = saved.page;
        warnings = saved.warnings;
        setEditorAssets([]);
      }
      const result = await api.publishTeacherBookPage(workspaceId, selectedId, draft.revision);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      const warningMessage = warnings.length > 0 ? `提示：${warnings.join("；")}` : "";
      setMessage(`教材已发布，学生端现在可以读取这一版正文。${warningMessage ? ` ${warningMessage}` : ""}`);
      await loadNavigation();
    } catch (reason) {
      setMessage(`发布失败：${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleFile = async (files: File[]) => {
    const markdownFiles = files.filter((file) => file.name.toLowerCase().endsWith(".md"));
    if (markdownFiles.length !== 1) {
      setMessage("请同时选择且只能选择一个 Markdown 文件；图片可一并选择。 ");
      return;
    }
    const file = markdownFiles[0];
    setMessage("");
    try {
      const assets = await Promise.all(files.filter((item) => item !== file).map(async (asset) => ({
        asset_path: assetPathForFile(asset),
        media_type: asset.type,
        content_base64: await fileToBase64(asset),
      })));
      const nextPreview = await api.previewTeacherBookImport(workspaceId, file.name, await file.text());
      setImportName(file.name);
      setImportAssets(assets);
      setImportPreview(nextPreview);
    } catch (reason) {
      setMessage(`导入预览失败：${reason instanceof Error ? reason.message : String(reason)}`);
    }
  };

  const handleEditorAssets = async (files: File[]) => {
    if (files.length === 0) return;
    setMessage("");
    try {
      const assets = await Promise.all(files.map(async (file) => ({
        asset_path: assetPathForFile(file),
        media_type: file.type,
        content_base64: await fileToBase64(file),
      })));
      setEditorAssets((current) => {
        const byPath = new Map(current.map((asset) => [asset.asset_path, asset]));
        assets.forEach((asset) => byPath.set(asset.asset_path, asset));
        return Array.from(byPath.values());
      });
      setMessage(`已附加 ${assets.length} 个图片资源，保存草稿时会自动入库并重写 Markdown 图片地址。`);
    } catch (reason) {
      setMessage(`图片资源读取失败：${reason instanceof Error ? reason.message : String(reason)}`);
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
      const result = await api.applyTeacherBookImport(workspaceId, selectedId, importName, importPreview.content_markdown, page.revision, importAssets);
      setPage(result.page);
      setContent(result.page.draft_markdown);
      setImportPreview(null);
      setImportAssets([]);
      setEditorAssets([]);
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
        <label className="teacher-book-import"><Upload size={15} />导入 Markdown/图片<input type="file" multiple accept=".md,text/markdown,image/png,image/jpeg,image/webp,image/gif" onChange={(event) => { void handleFile(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} /></label>
        <label className="teacher-book-import"><Upload size={15} />附加编辑图片<input type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => { void handleEditorAssets(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} /></label>
        <label className="teacher-book-import"><Upload size={15} />导入教材包<input type="file" accept=".zip,application/zip" onChange={(event) => { void handleArchiveFile(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
        <button type="button" onClick={() => void loadNavigation()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""} />刷新目录</button>
        {message && <span role="status">{message}</span>}
      </div>
      {importPreview && <section className="teacher-book-import-preview" aria-label="Markdown 导入预览"><div><strong>{importName}</strong><span>{importPreview.removed_frameworks.length ? `已过滤：${importPreview.removed_frameworks.join("、")}` : "未发现需要过滤的框架代码"}</span>{importAssets.length > 0 && <small>将一并保存 {importAssets.length} 个图片资源</small>}{importPreview.warnings.map((warning) => <small key={warning}>{warning}</small>)}<details><summary>查看规范化后的 Markdown</summary><pre>{importPreview.content_markdown}</pre></details></div><button type="button" onClick={() => void applyImport()} disabled={saving}><FileUp size={15} />应用到当前草稿</button></section>}
      {archivePreview && <section className="teacher-book-import-preview teacher-book-archive-preview" aria-label="教材包导入预览">
        <div className="teacher-book-archive-summary"><strong>{archivePreview.title}</strong><span>{archiveName} · {archivePreview.items.length} 个待检查知识点 · {archivePreview.asset_paths.length} 个图片资源</span>{archivePreview.warnings.map((warning) => <small key={warning}>{warning}</small>)}</div>
        <div className="teacher-book-archive-items">{archivePreview.items.map((item) => <div className={`teacher-book-archive-item ${item.action}`} key={item.knowledge_point_id}><span className="teacher-book-archive-action">{item.action === "create" ? "新增草稿" : item.action === "update" ? "覆盖草稿" : "内容未变"}</span><strong>{item.title}</strong><small>{item.file_name} · 版本 {item.expected_revision}</small>{item.removed_frameworks.length > 0 && <small>已过滤：{item.removed_frameworks.join("、")}</small>}{item.warnings.map((warning) => <small key={warning}>{warning}</small>)}{item.action === "update" && <details><summary>查看前后内容</summary><div className="teacher-book-diff"><pre>{item.current_markdown}</pre><pre>{item.content_markdown}</pre></div></details>}</div>)}</div>
        {archivePreview.omitted_knowledge_points.length > 0 && <small>未包含的目录知识点不会被删除：{archivePreview.omitted_knowledge_points.length} 个</small>}
        <div className="teacher-book-archive-actions"><button type="button" onClick={() => setArchivePreview(null)} disabled={saving}>取消</button><button type="button" onClick={() => void applyArchive()} disabled={saving || (archivePreview.items.every((item) => item.action === "unchanged") && archivePreview.asset_paths.length === 0)}><FileUp size={15} />确认应用到草稿</button></div>
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
            {editorAssets.length > 0 && <small className="teacher-book-editor-assets">已附加 {editorAssets.length} 个图片资源，保存时会写入当前知识点的教材资源。</small>}
            {preview ? <div className="teacher-book-preview"><MarkdownContent>{content || "暂无内容"}</MarkdownContent></div> : <textarea className="teacher-book-textarea" aria-label="教材正文 Markdown" value={content} onChange={(event) => setContent(event.target.value)} placeholder="# 知识点标题\n\n在这里编写面向学生的长篇教材正文。代码块建议使用 ```python，并只保留 PyTorch 示例。" />}
          </> : <div className="teacher-state"><BookOpenText /><p>选择一个知识点开始编写教材。</p></div>}
        </main>
      </div>
    </div>
  );
}
