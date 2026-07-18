import { Children, lazy, Suspense, type ReactNode } from "react";
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
      return <SyntaxHighlighter language={language} style={dark ? oneDark : oneLight} customStyle={{ margin: 0, borderRadius: "0 0 12px 12px", fontSize: 13 }}>{code}</SyntaxHighlighter>;
    },
  };
});

function headingText(children: ReactNode): string {
  return Children.toArray(children).join("");
}

export function MarkdownContent({ children, streaming = false }: { children: string; streaming?: boolean }) {
  const dark = document.documentElement.classList.contains("dark");
  return (
    <div className="prose prose-zinc max-w-none dark:prose-invert prose-headings:scroll-mt-20 prose-pre:p-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h2: ({ children: value }) => {
            const text = headingText(value);
            const educational = /练习|思考|核心|概念|误区|总结/.test(text);
            return <h2 className={educational ? "education-heading" : undefined}>{value}</h2>;
          },
          code: ({ className, children: value, ...props }) => {
            const match = /language-([\w-]+)/.exec(className ?? "");
            const content = String(value).replace(/\n$/, "");
            if (!match) return <code className={className} {...props}>{value}</code>;
            return (
              <div className="code-shell">
                <div className="code-label">{match[1]}</div>
                <Suspense fallback={<pre><code>{content}</code></pre>}>
                  <LazyCode language={match[1]} code={content} dark={dark} />
                </Suspense>
              </div>
            );
          },
          a: ({ children: value, ...props }) => <a {...props} target="_blank" rel="noreferrer">{value}</a>,
        }}
      >
        {children || (streaming ? "" : "暂无内容")}
      </ReactMarkdown>
      {streaming && <span className="stream-caret" aria-label="正在生成" />}
    </div>
  );
}
