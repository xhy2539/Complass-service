from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.kb.loader import load_reverse_rule_cases
from app.kb.retriever import DEFAULT_PERSIST_DIR
from app.kb.retriever import build_reverse_rule_kb


def main() -> None:
    cases = load_reverse_rule_cases()
    index_path = build_reverse_rule_kb(cases, DEFAULT_PERSIST_DIR)
    modules = {case.review_module for case in cases}
    print(f"reverse_rule_cases={len(cases)}")
    print(f"review_modules={len(modules)}")
    print(f"persisted_index={index_path}")


if __name__ == "__main__":
    main()
