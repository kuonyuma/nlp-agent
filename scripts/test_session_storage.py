from server.agent.session_storage import TranscriptMessage


def test_transcript_message_round_trip():
    record = TranscriptMessage(
        uuid="user-1",
        parentUuid=None,
        sessionId="session-1",
        type="user",
        role="user",
        content="请分析这段文本",
    )
    restored = TranscriptMessage.model_validate_json(record.model_dump_json())
    assert restored.uuid == "user-1"
    assert restored.content == "请分析这段文本"

