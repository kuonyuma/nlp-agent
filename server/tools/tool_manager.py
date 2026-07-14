from server.tools.api.file_read_tool import read_local_file
from server.tools.api.time_tool import get_current_time
from server.tools.api.web_search_tool import web_search


ALL_AVAILABLE_TOOLS = [
    read_local_file,
    get_current_time,
    web_search,
]


def _register_compactable_tools() -> None:
    """注册可安全重取结果的通用工具。"""

    try:
        from server.agent.compression.micro_compact import register_compactable_tool

        for tool in ALL_AVAILABLE_TOOLS:
            register_compactable_tool(tool.name)
    except Exception:
        pass


_register_compactable_tools()

