import os

from langchain_core.messages import SystemMessage

from server.memory.manager import INDEX_FILENAME, MEMORY_DIR, MemoryManager


_CACHED_MESSAGE = None
_LAST_MTIME = 0.0


def get_memory_system_message() -> SystemMessage:
    global _CACHED_MESSAGE, _LAST_MTIME
    index_path = os.path.join(MEMORY_DIR, INDEX_FILENAME)
    mtime = os.path.getmtime(index_path) if os.path.exists(index_path) else 0.0
    if _CACHED_MESSAGE is not None and mtime == _LAST_MTIME:
        return _CACHED_MESSAGE

    index = MemoryManager().load_memory_index()
    content = f"""## 长期记忆指南
系统会在后台自动提取并按需召回长期有价值的信息。你可以使用注入到上下文中的记忆，
但不要声称记住了索引之外的内容，也不要主动读写记忆文件。

当前记忆索引：
```markdown
{index}
```
"""
    _CACHED_MESSAGE = SystemMessage(content=content)
    _LAST_MTIME = mtime
    return _CACHED_MESSAGE

