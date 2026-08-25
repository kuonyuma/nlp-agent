import io
import json
import zipfile

import pytest

from gateway.repository import GatewayRepository
from server.teacher.archive import parse_teacher_book_archive


def make_archive(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


def manifest(file_name: str = "topics/basic/attention.md") -> bytes:
    return json.dumps({
        "format_version": 1,
        "title": "Nova 教材",
        "topics": [{"id": "basic", "name": "基础", "knowledge_points": [{"id": "attention", "name": "注意力", "file": file_name}]}],
    }, ensure_ascii=False).encode("utf-8")


def test_archive_parser_filters_frameworks_and_rewrites_local_images():
    parsed = parse_teacher_book_archive(
        "nova-book.zip",
        make_archive(
            {
                "manifest.json": manifest(),
                "topics/basic/attention.md": (
                    "# 注意力\n\n![图示](../../assets/attention.png)\n\n"
                    "```python\n#@tab tensorflow\ntf.nn.softmax(x)\n#@tab pytorch\n"
                    "torch.softmax(x, dim=-1)\n```"
                ).encode("utf-8"),
                "assets/attention.png": b"png-bytes",
            }
        ),
        workspace_id="workspace-1",
    )

    assert parsed.pages[0].knowledge_point_id == "attention"
    assert "tf.nn.softmax" not in parsed.pages[0].content_markdown
    assert "torch.softmax" in parsed.pages[0].content_markdown
    assert "/api/v1/learning/book/workspace-1/assets/assets/attention.png" in parsed.pages[0].content_markdown
    assert parsed.assets[0].media_type == "image/png"


@pytest.mark.parametrize(
    "file_name",
    ["../outside.md", "/outside.md", "topics\\..\\outside.md"],
)
def test_archive_parser_rejects_path_traversal(file_name):
    with pytest.raises(ValueError, match="路径"):
        parse_teacher_book_archive(
            "nova-book.zip",
            make_archive(
                {
                    "manifest.json": manifest(file_name),
                    file_name: b"# unsafe",
                }
            ),
            workspace_id="workspace-1",
        )


def test_archive_parser_rejects_unsupported_svg_resource():
    with pytest.raises(ValueError, match="不支持的文件"):
        parse_teacher_book_archive(
            "nova-book.zip",
            make_archive(
                {
                    "manifest.json": manifest(),
                    "topics/basic/attention.md": b"# attention",
                    "assets/diagram.svg": b"<svg></svg>",
                }
            ),
            workspace_id="workspace-1",
        )


def test_repository_batch_import_is_atomic_and_persists_assets(tmp_path):
    repository = GatewayRepository(tmp_path / "gateway.sqlite3")
    repository.apply_knowledge_book_import(
        "workspace-1",
        [{"knowledge_point_id": "attention", "expected_revision": 0, "content_markdown": "# v1\n\n![a](/api/v1/learning/book/workspace-1/assets/assets/a.png)"}],
        [{"asset_path": "assets/a.png", "media_type": "image/png", "content": b"a", "sha256": "a" * 64}],
    )

    with pytest.raises(ValueError, match="版本冲突"):
        repository.apply_knowledge_book_import(
            "workspace-1",
            [
                {"knowledge_point_id": "attention", "expected_revision": 0, "content_markdown": "# stale"},
                {"knowledge_point_id": "new", "expected_revision": 0, "content_markdown": "# should not land"},
            ],
            [],
        )

    assert repository.get_knowledge_page("workspace-1", "attention")["draft_markdown"].startswith("# v1")
    assert repository.get_knowledge_page("workspace-1", "new") is None
    repository.publish_knowledge_page("workspace-1", "attention", expected_revision=1)
    assert repository.get_knowledge_book_asset("workspace-1", "assets/a.png")["content"] == b"a"
    repository.close()
