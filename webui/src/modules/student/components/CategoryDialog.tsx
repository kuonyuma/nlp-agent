import { FolderPlus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

export function CategoryDialog({ open, onClose, onConfirm }: { open: boolean; onClose: () => void; onConfirm: (name: string) => void }) {
  const [name, setName] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const close = useCallback(() => {
    setName("");
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => input.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, open]);

  if (!open) return null;
  const value = name.trim();
  const submit = () => {
    if (!value) return;
    onConfirm(value);
    close();
  };

  return <div className="dialog-backdrop category-dialog-backdrop" role="presentation" onMouseDown={close}>
    <section className="category-dialog" role="dialog" aria-modal="true" aria-labelledby="category-dialog-title" aria-describedby="category-dialog-description" onMouseDown={(event) => event.stopPropagation()}>
      <header><span className="category-dialog-icon" aria-hidden="true"><FolderPlus size={20} /></span><div><h2 id="category-dialog-title">新建分类</h2><p id="category-dialog-description">用分类整理不同主题的学习对话，之后可随时重命名或删除。</p></div><button className="category-dialog-close" type="button" aria-label="关闭新建分类" onClick={close}><X size={17} /></button></header>
      <form onSubmit={(event) => { event.preventDefault(); submit(); }}><label htmlFor="category-name">分类名称</label><input ref={input} id="category-name" value={name} maxLength={40} onChange={(event) => setName(event.target.value)} placeholder="例如：Transformer 学习" autoComplete="off" /><small>{value ? `${value.length}/40` : "最多 40 个字符"}</small><footer><button className="category-dialog-cancel" type="button" onClick={close}>取消</button><button className="category-dialog-confirm" type="submit" disabled={!value}><FolderPlus size={16} />创建分类</button></footer></form>
    </section>
  </div>;
}
