"""Regression tests for asynchronous task state and Coze fallback behavior."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_route(path: str) -> str:
    """Read a route file as UTF-8 for lightweight behavior regression checks."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_review_task_commits_processing_before_heavy_work():
    source = _read_route("app/api/v1/contract_review_routes.py")

    processing_pos = source.index("task.status = TaskStatus.PROCESSING")
    commit_pos = source.index("db.commit()", processing_pos)
    parse_pos = source.index("DocumentParser.parse", processing_pos)

    assert processing_pos < commit_pos < parse_pos


def test_comparison_task_commits_processing_before_heavy_work():
    source = _read_route("app/api/v1/contract_comparison_routes.py")

    processing_pos = source.index("task.status = TaskStatus.PROCESSING")
    commit_pos = source.index("db.commit()", processing_pos)
    parse_pos = source.index("DocumentParser.parse", processing_pos)

    assert processing_pos < commit_pos < parse_pos


def test_coze_failures_are_downgraded_for_review_and_comparison():
    review_source = _read_route("app/api/v1/contract_review_routes.py")
    comparison_source = _read_route("app/api/v1/contract_comparison_routes.py")

    assert "AI 分析失败" in review_source
    assert "[Comparison] Coze 增强失败" in comparison_source
    assert "task.status = TaskStatus.COMPLETED" in review_source
    assert "task.status = TaskStatus.COMPLETED" in comparison_source


def test_async_tasks_persist_upload_paths_for_recovery():
    review_source = _read_route("app/api/v1/contract_review_routes.py")
    comparison_source = _read_route("app/api/v1/contract_comparison_routes.py")
    compose_source = _read_route("docker-compose.yml")

    assert "file_path=file_path" in review_source
    assert "old_file_path=old_file_path" in comparison_source
    assert "new_file_path=new_file_path" in comparison_source
    assert "./task_uploads:/app/task_uploads" in compose_source
