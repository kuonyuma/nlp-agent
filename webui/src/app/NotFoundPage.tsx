import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="boot-screen error">
      <h1>页面未找到</h1>
      <p>这个地址不存在，或页面已经移动。</p>
      <Link to="/">
        <ArrowLeft size={16} />
        返回学生空间
      </Link>
    </main>
  );
}
