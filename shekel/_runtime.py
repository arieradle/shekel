"""ShekelRuntime — framework detection and adapter wiring (v1.0.0).

Probed once at budget open. Activates any installed framework adapters
(LangGraph, CrewAI, OpenClaw, ...). The adapter list starts empty; later
phases register into it via ShekelRuntime.register().
"""

from __future__ import annotations

from typing import Any


class ShekelRuntime:
    """Detects installed framework adapters and wires them at budget open/close.

    Usage (internal — called by Budget.__enter__ / __exit__)::

        runtime = ShekelRuntime(budget_instance)
        runtime.probe()    # on __enter__
        runtime.release()  # on __exit__

    Framework adapters are registered once at import time by each phase::

        ShekelRuntime.register(LangGraphAdapter)   # v0.3.2
        ShekelRuntime.register(CrewAIAdapter)      # v0.3.3
    """

    _adapter_registry: list[type[Any]] = []

    def __init__(self, budget: Any) -> None:
        self._budget = budget
        self._active_adapters: list[Any] = []

    def probe(self) -> None:
        """Activate all registered framework adapters whose packages are installed.

        Called once on ``budget.__enter__()``. Adapters that raise
        ``ImportError`` are silently skipped (framework not installed).
        """
        for adapter_cls in ShekelRuntime._adapter_registry:
            try:
                adapter = adapter_cls()
                adapter.install_patches(self._budget)
                self._active_adapters.append(adapter)
            except ImportError:
                pass  # framework not installed — silent skip

    def release(self) -> None:
        """Deactivate all adapters that were activated by probe().

        Called once on ``budget.__exit__()``. Exceptions from
        ``remove_patches()`` are suppressed to avoid masking the original
        exception during budget exit.
        """
        for adapter in self._active_adapters:
            try:
                adapter.remove_patches(self._budget)
            except Exception:  # pragma: no cover — defensive cleanup
                pass
        self._active_adapters.clear()

    @classmethod
    def register(cls, adapter_cls: type[Any]) -> None:
        """Register a framework adapter class.

        Called once per phase at module import time::

            ShekelRuntime.register(LangGraphAdapter)
        """
        cls._adapter_registry.append(adapter_cls)


# ---------------------------------------------------------------------------
# Built-in framework adapters — registered once at import time
# ---------------------------------------------------------------------------


def _register_builtin_adapters() -> None:
    from shekel.providers.crewai import CrewAIExecutionAdapter  # noqa: PLC0415
    from shekel.providers.langchain import LangChainRunnerAdapter  # noqa: PLC0415
    from shekel.providers.langgraph import LangGraphAdapter  # noqa: PLC0415

    ShekelRuntime.register(LangGraphAdapter)
    ShekelRuntime.register(LangChainRunnerAdapter)
    ShekelRuntime.register(CrewAIExecutionAdapter)


_register_builtin_adapters()
