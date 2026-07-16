# 模型抽象层

NLP Agent 从 `v0.14.0` 起使用显式 Provider Registry 和类型化模型路由。Coordinator、Worker、Memory 与 Compression 不再直接构造 DeepSeek/OpenAI SDK 对象。

## 四层配置

`configs/agent_config.yaml` 将模型配置拆成四层：

1. `providers`：连接协议、Endpoint、密钥环境变量和固定 Header；
2. `models`：真实模型 ID、上下文窗口、最大输出和能力声明；
3. `model_presets`：思考、生成、超时、重试和熔断策略；
4. `model_routes`：Coordinator、Worker、Utility 的主模型和 fallback 链。

Provider 和 Model 必须显式关联，不通过 URL 或模型名称猜测 Provider。

## 默认 DeepSeek 路由

```text
coordinator: coordinator-pro (V4 Pro/max) -> coordinator-fast (V4 Flash/high)
worker:      worker-flash (V4 Flash/high) -> worker-pro (V4 Pro/high)
utility:     utility-flash (V4 Flash/non-thinking)
```

Utility 用于记忆整理、Context Collapse 和 Auto Compact，避免为确定性摘要支付 Pro/max 的延迟与 Token。

DeepSeek 思考模式通过 `extra_body.thinking.type` 控制。内部统一 effort 枚举为 `none/low/medium/high/max`；DeepSeek Adapter 将 low、medium、high 映射为 `high`，将 max 映射为 `max`。思考模式下会丢弃无效的 temperature/top_p。

## 运行语义

`ResilientChatModel` 保持 LangChain 的 `bind_tools()`、`with_structured_output()`、`ainvoke()` 和 `astream()` 调用形态。普通 `ainvoke()` 内部也使用统一流式路径，确保首 Token、流空闲和总超时具有相同语义。

重试仅覆盖超时、连接错误、408/409/429 和 5xx。400/401/403/404、上下文超限、非法工具 Schema、余额和配额错误不会重试或 fallback。SDK 自带重试固定为 0，避免双重重试。

流式调用遵守：

- 首个可见 delta 前失败，可以重试或 fallback；
- 已输出正文、reasoning 或工具调用 delta 后失败，抛出 `StreamInterruptedError`；
- 不会把新模型从头生成的内容静默拼接到已有流；
- reasoning、content、tool argument 和 usage chunk 都能维持流活性。

Fallback 在配置加载时验证 streaming/tool-call 能力。上下文预算使用整条候选链的最小窗口，并为候选链最大输出预留空间。

## DeepSeek 工具调用

DeepSeek thinking 模式下，包含工具调用的 Assistant 消息必须回传 `reasoning_content`。`DeepSeekChatModel` 只为此类消息注入 reasoning；普通完成轮次不回传，从而保持请求前缀稳定。

工具调用仍使用 LangChain 标准 `AIMessage.tool_calls` 与 `AIMessageChunk.tool_call_chunks`，后续由 Tool Runtime 执行 Pydantic 参数校验。模型层不会修复或猜测可执行参数。

## KV Cache

DeepSeek 服务端 Context/KV Cache 自动启用，本地不保存 KV 数据。统一 usage 支持：

```text
input_tokens
output_tokens
total_tokens
cached_tokens / cache_read
cache_miss_tokens
reasoning_tokens
```

Provider 原始 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens` 会进入模型 Span、Trace 和每日指标。Worker 的固定协议与 SOP 和动态时间已拆成不同消息，以提高相同 Profile 的稳定前缀命中率。

## 扩展 Provider

新 Provider 只需实现 Adapter 并注册：

```python
from core.model_runtime.registry import global_provider_registry

global_provider_registry.register("custom", CustomAdapter)
```

Adapter 返回 LangChain 兼容 Chat Model，负责 Provider 请求参数和响应元数据差异；重试、fallback、熔断、观测和流式保护由 `ResilientChatModel` 统一负责。

## 观测事件

每次 Provider 尝试产生 `model.request` Span，包含 provider、model、preset、attempt、fallback index、thinking、reasoning effort、TTFT、Token 和缓存指标。

运行时还会产生：

```text
model.retry
model.failover
model.circuit_open
model.stream_interrupted
```

未来 Gateway/WebUI 继续通过 `ObservabilityService` 查询，无需理解具体 Provider SDK。
