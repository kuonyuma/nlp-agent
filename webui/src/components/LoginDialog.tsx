import * as Dialog from "@radix-ui/react-dialog";
import { LockKeyhole, X } from "lucide-react";
import { FormEvent, useState } from "react";

export function LoginDialog({
  open,
  onClose,
  onAuthenticate,
}: {
  open: boolean;
  onClose: () => void;
  onAuthenticate: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const close = () => {
    setPassword("");
    setError("");
    setSubmitting(false);
    onClose();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await onAuthenticate(username.trim(), password);
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) close(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="login-dialog-overlay" />
      <Dialog.Content className="login-dialog-content" aria-describedby="login-dialog-description">
        <button className="login-dialog-close" type="button" onClick={close} aria-label="关闭登录"><X size={18} /></button>
        <Dialog.Title>登录 Nova</Dialog.Title>
        <Dialog.Description id="login-dialog-description">登录后可创建学习会话并使用实时对话功能。</Dialog.Description>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            <span>账号</span>
            <input autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} disabled={submitting} maxLength={128} required />
          </label>
          <label>
            <span>密码</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={submitting} maxLength={512} required />
          </label>
          {error && <p className="login-dialog-error" role="alert">{error}</p>}
          <button className="login-dialog-submit" type="submit" disabled={submitting || !username.trim() || !password}>
            <LockKeyhole size={16} />{submitting ? "正在验证" : "登录并继续"}
          </button>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
