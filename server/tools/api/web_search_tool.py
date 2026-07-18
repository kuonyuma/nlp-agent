import json
from typing import Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from configs.settings import settings
from utils.logger import get_logger


logger = get_logger("nlp_agent.tools.web_search")
TAVILY_BASE_URL = "https://api.tavily.com/search"


class WebSearchInput(BaseModel):
    query: str = Field(..., description="搜索问题或关键词")
    max_results: int = Field(default=5, ge=1, le=10)


class SearchResultItem(BaseModel):
    title: str
    url: str
    content: str
    score: Optional[float] = None


class WebSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total_results: int


@tool("web_search", args_schema=WebSearchInput)
async def web_search(query: str, max_results: int = 5) -> str:
    """搜索需要最新公开信息或外部资料的问题。"""

    api_key = settings.secret_value("TAVILY_API_KEY")
    if not api_key:
        return '{"error":"TAVILY_API_KEY 未配置"}'
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TAVILY_BASE_URL, json=payload)
            response.raise_for_status()
        results = [SearchResultItem(**item) for item in response.json().get("results", [])]
        return WebSearchResponse(
            query=query,
            results=results,
            total_results=len(results),
        ).model_dump_json()
    except Exception as error:
        logger.exception("Web search failed", error=str(error))
        return json.dumps({"error": str(error)}, ensure_ascii=False)
