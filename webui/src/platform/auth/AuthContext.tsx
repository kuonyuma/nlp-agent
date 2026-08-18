import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ensureAuth } from "@/platform/http/api";
import type { AuthSession } from "@/shared/types";

interface AuthContextValue {
  user: AuthSession | null;
  roles: string[];
  logout: () => Promise<void>;
  loading: boolean;
  error: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * 全局鉴权上下文（满足 review 文档 8.3）。
 * 启动时 bootstrap session，统一暴露 user/roles 与 logout。
 * 注意：前端只做体验，真实权限以服务端返回的 permissions / capabilities 为准。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    ensureAuth()
      .then((session) => {
        if (active) setUser(session);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "认证失败");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, roles: user?.roles ?? [], logout, loading, error }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth 必须在 <AuthProvider> 内部使用");
  }
  return ctx;
}
