"""Performance test configuration.

All performance tests run in a single xdist worker to avoid timing
interference from parallel load. The group name "perf" ensures pytest-xdist
schedules them together.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "performance" in str(item.fspath):
            item.add_marker(pytest.mark.xdist_group("perf"))
