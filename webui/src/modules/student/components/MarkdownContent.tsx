import { Check, Copy, ExternalLink, MessageCircleQuestion } from "lucide-react";
import { Children, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import "katex/dist/katex.min.css";

const LazyCode = lazy(async () => {
  const [{ default: SyntaxHighlighter }, { default: oneDark }, { default: oneLight }] = await Promise.all([
    import("react-syntax-highlighter/dist/esm/prism-async-light"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    import("react-syntax-highlighter/dist/esm/styles/prism/one-light"),
  ]);
  return {
    default({ language, code, dark }: { language: string; code: string; dark: boolean }) {
      return <SyntaxHighlighter language={language} style={dark ? oneDark : oneLight} customStyle={{ margin: 0, borderRadius: 0, fontSize: 14, background: dark ? "#202124" : "#f3f4f6" }}>{code}</SyntaxHighlighter>;
    },
  };
});

export interface MarkdownCodeActions {
  onAskNova?: (code: string, language: string) => void;
  onOpenInSandbox?: (code: string, language: string) => void;
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "true");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand("copy");
  input.remove();
  if (!copied) throw new Error("clipboard copy failed");
}

function LessonCodeBlock({ code, dark, language, actions }: { code: string; dark: boolean; language: string; actions?: MarkdownCodeActions }) {
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">("idle");
  const [codeReady, setCodeReady] = useState(() => typeof IntersectionObserver === "undefined");
  const codeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (copyStatus === "idle") return undefined;
    const timer = window.setTimeout(() => setCopyStatus("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [copyStatus]);

  useEffect(() => {
    if (codeReady) return undefined;
    const target = codeRef.current;
    if (!target || typeof IntersectionObserver === "undefined") {
      setCodeReady(true);
      return undefined;
    }
    const root = target.closest<HTMLElement>(".knowledge-book-page-scroll,.teacher-book-preview");
    // happy-dom does not calculate layout boxes, so IntersectionObserver never
    // reports an intersection there. Render the code immediately in that
    // environment while keeping the viewport-gated path in a real browser.
    if (root && root.getBoundingClientRect().height === 0) {
      setCodeReady(true);
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setCodeReady(true);
        observer.disconnect();
      }
    }, { root, rootMargin: "640px 0px", threshold: 0 });
    observer.observe(target);
    return () => observer.disconnect();
  }, [codeReady]);

  const copy = async () => {
    try {
      await copyText(code);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
  };

  const supportsLessonActions = /^(?:python|pytorch|py)$/i.test(language);
  const lessonActions = supportsLessonActions ? actions : undefined;
  return <div ref={codeRef} className="code-shell">
    <div className="code-toolbar">
      <div className="code-label">{language}</div>
      {lessonActions && <div className="code-actions">
        <button type="button" aria-label={`${copyStatus === "copied" ? "已复制" : "复制"} ${language} 代码`} onClick={() => void copy()}>{copyStatus === "copied" ? <Check size={13} /> : <Copy size={13} />}{copyStatus === "copied" ? "已复制" : "复制"}</button>
        {lessonActions.onAskNova && <button type="button" aria-label="问 Nova" onClick={() => lessonActions.onAskNova?.(code, language)}><MessageCircleQuestion size={13} />问 Nova</button>}
        {lessonActions.onOpenInSandbox && <button type="button" aria-label="在沙箱中打开" onClick={() => lessonActions.onOpenInSandbox?.(code, language)}><ExternalLink size={13} />在沙箱中打开</button>}
        <span className="sr-only" aria-live="polite">{copyStatus === "copied" ? `已复制 ${language} 代码` : copyStatus === "error" ? `复制 ${language} 代码失败` : ""}</span>
        {copyStatus === "error" && <span className="code-action-status" role="status">复制失败</span>}
      </div>}
    </div>
    {codeReady ? <Suspense fallback={<pre><code>{code}</code></pre>}><LazyCode language={language} code={code} dark={dark} /></Suspense> : <pre className="code-lazy-fallback"><code>{code}</code></pre>}
  </div>;
}

function headingText(children: ReactNode): string {
  return Children.toArray(children).join("");
}

function headingSourceLine(node: unknown): number | undefined {
  if (!node || typeof node !== "object") return undefined;
  const position = (node as { position?: { start?: { line?: unknown } } }).position;
  const line = position?.start?.line;
  return typeof line === "number" ? line : undefined;
}

function normalizeFormulaContent(content: string): string {
  return content.replace(/(?<!\\)\|([^|\r\n]+?)(?<!\\)\|/g, "\\lvert $1\\rvert");
}

function normalizeFormulaDelimiters(text: string): string {
  const withDollarDelimiters = text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, content: string) => `$$\n${normalizeFormulaContent(content.trim())}\n$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, content: string) => `$${normalizeFormulaContent(content)}$`);
  return withDollarDelimiters.replace(/\$([^$\r\n]+)\$/g, (_match, content: string) => `$${normalizeFormulaContent(content)}$`);
}

function normalizeTextOutsideCode(text: string): string {
  return text.split(/(`+[\s\S]*?`+)/g).map((segment, index) => index % 2 ? segment : normalizeFormulaDelimiters(segment)).join("");
}

function normalizeLatexDelimiters(markdown: string): string {
  let result = "";
  let cursor = 0;
  const fenceStart = /^(?: {0,3})(`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)/gm;
  let opening: RegExpExecArray | null;

  while ((opening = fenceStart.exec(markdown))) {
    if (opening.index < cursor) continue;
    result += normalizeTextOutsideCode(markdown.slice(cursor, opening.index));
    const marker = opening[1];
    const fenceEnd = new RegExp(`^(?: {0,3})${marker[0]}{${marker.length},}[^\\r\\n]*(?:\\r?\\n|$)`, "gm");
    fenceEnd.lastIndex = opening.index + opening[0].length;
    const closing = fenceEnd.exec(markdown);
    if (!closing) return result + markdown.slice(opening.index);
    result += markdown.slice(opening.index, fenceEnd.lastIndex);
    cursor = fenceEnd.lastIndex;
    fenceStart.lastIndex = cursor;
  }

  return result + normalizeTextOutsideCode(markdown.slice(cursor));
}

function isSameOriginMarkdownLink(href: string | undefined): href is string {
  if (!href) return false;
  if (href.startsWith("#")) return true;
  if (!href.startsWith("/")) return false;
  if (/\\|%5c/i.test(href)) return false;
  try {
    return new URL(href, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

function isSafeMarkdownImage(src: string | undefined, allowDataImages = false): src is string {
  if (!src || src.startsWith("#")) return false;
  if (/^data:/i.test(src)) return allowDataImages && /^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(src);
  try {
    return new URL(src, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

function readMarkdownImageWidth(title: string | undefined): string | undefined {
  const match = title?.trim().match(/^width\s*=\s*(\d+(?:\.\d+)?)(px|%|rem|em|vw|vh)?$/i);
  if (!match) return undefined;
  const value = Number(match[1]);
  const unit = (match[2] ?? "px").toLowerCase();
  const maximum = unit === "%" || unit === "vw" || unit === "vh" ? 100 : 1600;
  if (!Number.isFinite(value) || value <= 0 || value > maximum) return undefined;
  return `${value}${unit}`;
}

/** Internal protocol metadata is parsed by the gateway and must never be shown or copied as lesson content. */
export function stripInternalChatMetadata(content: string): string {
  return content.replace(/\s*<!--\s*guided-result\s*:\s*(?:\{[\s\S]*?\}\s*-->|[\s\S]*$)/gi, "").trimEnd();
}

export function MarkdownContent({ children, streaming = false, headingIds, headingIdsByLine, codeActions, allowDataImages = false }: { children: string; streaming?: boolean; headingIds?: string[]; headingIdsByLine?: Record<number, string>; codeActions?: MarkdownCodeActions; allowDataImages?: boolean }) {
  const dark = document.documentElement.classList.contains("dark");
  const renderedMarkdown = useMemo(() => {
    let legacyHeadingIndex = 0;
    const nextHeadingId = (node: unknown) => {
      if (headingIdsByLine) {
        const sourceLine = headingSourceLine(node);
        return sourceLine === undefined ? undefined : headingIdsByLine[sourceLine];
      }
      return headingIds?.[legacyHeadingIndex++];
    };
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        urlTransform={(url) => url}
        components={{
          h1: ({ children: value, node, ...props }) => {
            const headingId = nextHeadingId(node);
            return <><span id={headingId} className="knowledge-book-heading-anchor" data-knowledge-book-heading-anchor="true" aria-hidden="true" /><h1 {...props} data-knowledge-book-heading-id={headingId}>{value}</h1></>;
          },
          h2: ({ children: value, node }) => {
            const headingId = nextHeadingId(node);
            const text = headingText(value);
            const educational = /练习|思考|核心|概念|误区|总结/.test(text);
            return <><span id={headingId} className="knowledge-book-heading-anchor" data-knowledge-book-heading-anchor="true" aria-hidden="true" /><h2 data-knowledge-book-heading-id={headingId} className={educational ? "education-heading" : undefined}>{value}</h2></>;
          },
          h3: ({ children: value, node, ...props }) => {
            const headingId = nextHeadingId(node);
            return <><span id={headingId} className="knowledge-book-heading-anchor" data-knowledge-book-heading-anchor="true" aria-hidden="true" /><h3 {...props} data-knowledge-book-heading-id={headingId}>{value}</h3></>;
          },
          h4: ({ children: value, node, ...props }) => {
            const headingId = nextHeadingId(node);
            return <><span id={headingId} className="knowledge-book-heading-anchor" data-knowledge-book-heading-anchor="true" aria-hidden="true" /><h4 {...props} data-knowledge-book-heading-id={headingId}>{value}</h4></>;
          },
          code: ({ className, children: value, ...props }) => {
            const match = /language-([\w-]+)/.exec(className ?? "");
            const content = String(value).replace(/\n$/, "");
            if (!match) return <code className={className} {...props}>{value}</code>;
            return <LessonCodeBlock language={match[1]} code={content} dark={dark} actions={codeActions} />;
          },
          a: ({ children: value, href, ...props }) => isSameOriginMarkdownLink(href)
            ? <a {...props} href={href}>{value}</a>
            : <span className="external-link-removed">{value}</span>,
          img: ({ node, src, alt, title, ...props }) => {
            void node;
            const imageWidth = readMarkdownImageWidth(title);
            return isSafeMarkdownImage(src, allowDataImages)
              ? <span className="markdown-image-figure"><img {...props} src={src} alt={alt ?? ""} title={imageWidth ? undefined : title} loading="lazy" decoding="async" style={imageWidth ? { ...props.style, width: imageWidth } : props.style} />{alt?.trim() && <span className="markdown-image-caption">{alt}</span>}</span>
              : <span className="external-link-removed">{alt || "图片资源不可用"}</span>;
          },
        }}
      >
        {normalizeLatexDelimiters(stripInternalChatMetadata(children) || (streaming ? "" : "暂无内容"))}
      </ReactMarkdown>
    );
  }, [allowDataImages, children, codeActions, dark, headingIds, headingIdsByLine, streaming]);

  return (
    <div className="markdown-content prose prose-zinc max-w-none dark:prose-invert prose-headings:scroll-mt-20 prose-pre:p-0">
      {renderedMarkdown}
      {streaming && <span className="stream-caret" aria-label="正在生成" />}
    </div>
  );
}
