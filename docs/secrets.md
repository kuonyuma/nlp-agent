# 本地密钥管理

项目使用 Pydantic Settings v2 加载配置，并使用 Windows 凭据管理器保存本地密钥。

- `SecretStr` 会在日志、调试输出和 `model_dump(mode="json")` 中自动脱敏。
- 密钥优先从 Windows 凭据管理器中读取；环境变量和 `.env` 仅作为首次迁移期间的兼容回退。
- 模型运行时、Tavily 工具和开发者页面均通过统一的密钥解析入口访问密钥；开发者页面只显示“已配置”。

首次从旧 `.env` 迁移：

```powershell
python main.py secrets migrate-env --remove-from-env
```

手动写入密钥（输入不会回显，也不会进入 shell 历史）：

```powershell
python main.py secrets set DEEPSEEK_API_KEY
python main.py secrets set NLP_AGENT_WEB_SECRET
```

首次在新电脑上配置多个密钥，可一次执行并按提示输入；不需要的项目直接回车跳过：

```powershell
uv run python main.py secrets setup
```

检查状态或删除一项密钥：

```powershell
python main.py secrets status
python main.py secrets delete DEEPSEEK_API_KEY
```

Windows 凭据管理器中的服务名为 `Pro_NLP`。不要把密钥重新写入 Git 或 `.env-example`。
