"""
测试 Context Collapse (Layer 4)
"""
import os
import sys
import pytest
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import asyncio
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from server.agent.compression.context_collapse import (
    CollapseStore,
    apply_collapses_if_needed,
    COMMIT_THRESHOLD,
    BLOCKING_THRESHOLD,
    EFFECTIVE_WINDOW,
)

# Mock LLM for summary generation to avoid actual API calls
import server.agent.compression.context_collapse as cc_module
async def mock_generate_summary(msgs):
    return "This is a mock summary of the span."

def make_human(content: str):
    return HumanMessage(content=content, id=str(uuid.uuid4()))

def make_ai(content: str):
    return AIMessage(content=content, id=str(uuid.uuid4()))

def make_system(content: str):
    return SystemMessage(content=content, id=str(uuid.uuid4()))

@pytest.mark.asyncio
async def test_context_collapse_flow(monkeypatch):
    monkeypatch.setattr(cc_module, "_generate_span_summary", mock_generate_summary)
    store = CollapseStore()
    
    # 构造一批消息，每条 20,000 tokens，凑够 160K (不到 162K)
    msgs = [make_system("Sys prompt")]
    for i in range(8):
        msgs.append(make_human(f"H{i}" * 20_000))
        msgs.append(make_ai(f"A{i}" * 10))
        
    # 总计约 8 * (20K/4) = 40K chars, Wait, 20_000 chars is ~5K tokens. 
    # Let's just make it huge.
    msgs = [make_system("Sys prompt")]
    for i in range(15):
        # 10_000 chars ~ 2.5K tokens per pair
        msgs.append(make_human(f"H{i}" * 10_000))
        msgs.append(make_ai(f"A{i}" * 10))
        
    # Test 1: Stage Phase
    # ~150K tokens, below COMMIT_THRESHOLD (162K)
    print("Testing Stage Phase...")
    token_count = cc_module.rough_estimation_for_messages(msgs)
    print(f"Token count is {token_count}")
    projected = await apply_collapses_if_needed(msgs, store)
    print(f"Staged span count: {len(store.staged)}")
    if len(store.staged) == 0:
        print(f"Messages total: {len(msgs)}")
    assert len(store.staged) > 0, "应生成 staged span"
    assert len(store.commits) == 0, "不应触发 commit"
    assert len(projected) == len(msgs), "Stage 阶段不改变消息列表视图"
    
    # Test 2: Commit Phase
    # Add more to trigger COMMIT_THRESHOLD (162K)
    for i in range(15):
        msgs.append(make_human(f"H_new{i}" * 40_000))
        msgs.append(make_ai(f"A_new{i}" * 10))
        
    print("Testing Commit Phase...")
    token_count2 = cc_module.rough_estimation_for_messages(msgs)
    print(f"Token count is {token_count2}")
    projected2 = await apply_collapses_if_needed(msgs, store)
    assert len(store.commits) > 0, "超过 162K，应触发部分 commit"
    # 验证 projected2 中原本的消息被替换为了 SystemMessage 的 collapse 标签
    has_collapse_tag = any(isinstance(m, SystemMessage) and "<collapsed" in m.content for m in projected2)
    assert has_collapse_tag, "视图中应包含 <collapsed> 标签"
    assert len(projected2) < len(msgs), "投影后的消息数应减少（因为多条被合并为一条）"
    
    # Test 3: Blocking Phase
    # Trigger 171K
    for i in range(10):
        msgs.append(make_human(f"H_block{i}" * 40_000))
        msgs.append(make_ai(f"A_block{i}" * 10))
        
    print("Testing Blocking Phase...")
    token_count3 = cc_module.rough_estimation_for_messages(msgs)
    print(f"Token count is {token_count3}")
    projected3 = await apply_collapses_if_needed(msgs, store)
    assert len(store.staged) == 0, "Blocking 排空后 staged 应当为空"
    assert len(store.commits) > 0, "commits 应增多"
    has_collapse_tag3 = any(isinstance(m, SystemMessage) and "<collapsed" in m.content for m in projected3)
    assert has_collapse_tag3

if __name__ == "__main__":
    asyncio.run(test_context_collapse_flow())
    print("All tests passed!")
