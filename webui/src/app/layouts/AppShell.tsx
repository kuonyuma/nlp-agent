import { Suspense } from "react";
import { Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <Suspense
      fallback={
        <div className="boot-screen" role="status">
          <span className="boot-orbit" />
          <strong>正在进入 NLP 学习空间</strong>
          <p>连接教学 Agent 与学习记录……</p>
        </div>
      }
    >
      <Outlet />
    </Suspense>
  );
}
