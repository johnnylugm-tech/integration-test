"""[FR-01] Task id generation.

Citations:
- 03-development/tests/test_fr01.py:20 (generate_task_id contract — 8 lowercase hex)
- SRS.md:1-22 (uuid4 前 8 hex)
"""
from __future__ import annotations

import uuid


def generate_task_id() -> str:
    """Return the first 8 lowercase hex chars of a uuid4.

    Citations:
    - 03-development/tests/test_fr01.py:92 (id 須符合 [0-9a-f]{8})
    - 03-development/tests/test_fr01.py:202-207 (uuid4 隨機性,連續兩個 id 不可相等)
    """
    return uuid.uuid4().hex[:8]
