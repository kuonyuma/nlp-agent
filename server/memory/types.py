MEMORY_TYPES = ["profile", "preference", "project", "feedback"]


def is_valid_memory_type(memory_type: str) -> bool:
    return memory_type in MEMORY_TYPES


def get_type_display_name(memory_type: str) -> str:
    return {
        "profile": "用户信息",
        "preference": "长期偏好",
        "project": "项目上下文",
        "feedback": "反馈与修正",
    }.get(memory_type, memory_type)

