import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
}

/** A shared, accessible confirmation dialog for destructive actions. */
export function ConfirmDialog({ open, title, description, confirmLabel = "确认删除", cancelLabel = "取消", onConfirm, onClose }: ConfirmDialogProps) {
  const cancelButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;
  return <div className="dialog-backdrop confirm-dialog-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description" onMouseDown={(event) => event.stopPropagation()}>
      <div className="confirm-dialog-icon" aria-hidden="true"><AlertTriangle size={20} /></div>
      <div className="confirm-dialog-copy"><h2 id="confirm-dialog-title">{title}</h2><p id="confirm-dialog-description">{description}</p></div>
      <footer><button ref={cancelButton} className="confirm-dialog-cancel" type="button" onClick={onClose}>{cancelLabel}</button><button className="confirm-dialog-destructive" type="button" onClick={onConfirm}>{confirmLabel}</button></footer>
    </section>
  </div>;
}
