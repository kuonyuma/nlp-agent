# 图片理解工具

Nova 通过统一工具运行时暴露 `image_analyze`。工具只授权给
`visual_researcher` Worker，并继续使用现有的工具预算、并发、超时、审计和
权限检查。

## 当前交付范围

本实现覆盖设计方案的阶段 1、阶段 3，以及阶段 5 的后端权限/提示词/测试部分：

- 统一的 Pydantic 输入、输出、引用、置信度和稳定错误码；
- JPEG、PNG、WebP 的真实解码、字节、尺寸、像素、帧数和损坏检查；
- 会话隔离的本地图片目录、路径穿越和符号链接/重解析点防护；
- `ocr`、`describe`、`question`、`table`、`chart`、`formula` 与可解释的
  `auto` 路由；
- 可注入的 OCR、VLM 和路由信号 Provider；
- 通过 Model Runtime route 调用具备 `vision` 与 `structured_output` 能力的
  VLM；
- 不可信图像边界、独立 OCR/VLM 置信度和安全引用；
- Web 与 Worker 在单机 Compose 中共享 `nova-data`，避免两个容器看到不同的
  `.data`；
- 视觉结果只在当前 Worker 推理内存中使用，不把原始 OCR/视觉 artifact 写入
  sidechain transcript。

阶段 1 不包含真实 OCR adapter。`tools.vision.ocr.provider=paddleocr` 是后续
adapter 的配置契约；调用依赖 OCR 的路由时会返回稳定的
`provider_unavailable`，不会回退到猜测结果。

## 输入目录与会话隔离

工具运行时从 `RunnableConfig` 获取并验证 `workspace_id`、`user_id` 和
`thread_id`，只允许读取：

```text
.data/uploads/<workspace_id>/<user_id>/<thread_id>/
```

模型可以传入该目录内的绝对路径或项目相对路径。响应只回显安全文件名、哈希、
媒体类型和尺寸，不回显本地绝对路径。缺少会话上下文时工具以
`session_context_required` 失败关闭。

首期默认拒绝 URL、GIF、SVG、PDF、TIFF、动画 WebP、低于 48 像素的图片、
超字节和超像素图片。文件扩展名和请求 Content-Type 均不作为可信格式依据。

## VLM 配置

`tools.vision.vlm.model_route` 默认指向 `vision-worker`。仓库已将它连接到
`qwen3-vl-plus` 的非思考模式 preset；启用时需要可访问该模型的 `QWEN_API_KEY`。
route 的全部候选模型必须显式声明：

```yaml
capabilities:
  vision: true
  structured_output: true
```

仓库现有文本模型没有被自动标记为视觉模型。若模型未获授权、route 缺失、能力
不匹配或密钥不可用，工具返回脱敏的 `provider_unavailable`。VLM 以 Base64 Data
URL 发送受控图片，不发送本地路径、Cookie、用户身份或任意请求头。

视觉 preset 的单次模型总超时为 80 秒，外层工具超时为 90 秒；工具运行时会把
持有该工具的 Worker 与 join wait 自动提高到足以覆盖工具调用的下限。视觉模型
route 只执行一次付费尝试，避免与工具层重试叠加。

## 部署边界

`nova-data` 是单机 Docker Compose 的共享卷方案。多主机或弹性 Worker 部署不能
依赖本地卷，需要先实现共享 AssetStore（如 S3/MinIO），并让工具接收不可猜测的
asset ID。

设计文档尚未定义 Web 上传 API、asset ownership 和聊天附件契约，因此本次没有
擅自增加前端附件功能。实现上传闭环时，上传端必须复用上述会话目录或 AssetStore
命名空间。当前本地会话删除流程会同步清理该会话的上传目录；未来 AssetStore 也
必须提供同等的所有权检查与删除语义。

## 验证

```powershell
uv run ruff check configs core gateway server tests scripts
uv run pytest tests/test_vision_safety.py tests/test_vision_router.py `
  tests/test_image_analyze_tool.py tests/test_vision_vlm.py
```
