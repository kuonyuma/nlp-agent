import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

interface Props { children: ReactNode }
interface State { error: Error | null }

/** Keep an unexpected view error actionable instead of leaving a blank page. */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State { return { error }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Pro_NLP WebUI render error", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <main className="app-error-boundary"><TriangleAlert size={30} /><h1>页面未能正常显示</h1><p>{this.state.error.message || "发生了未知界面错误。"}</p><button type="button" onClick={() => location.reload()}><RefreshCw size={16} />重新加载页面</button></main>;
  }
}
