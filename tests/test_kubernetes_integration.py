"""Tests for SHEK-16 / SHEK-17: Kubernetes auto-discovery and spend reporting.

All tests mock kubernetes.client.CoreV1Api — no live cluster required.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stop_k8s_threads() -> Iterator[None]:
    yield
    for thread in threading.enumerate():
        if thread.name.startswith("shekel-k8s-") and hasattr(thread, "stop"):
            thread.stop()


def _make_configmap(data: dict[str, str]) -> MagicMock:
    cm = MagicMock()
    cm.data = data
    return cm


def _make_k8s_mock(configmap_data: dict[str, str]) -> MagicMock:
    """Return a mock kubernetes module whose CoreV1Api returns the given ConfigMap."""
    k8s = MagicMock()
    api_instance = MagicMock()
    api_instance.read_namespaced_config_map.return_value = _make_configmap(configmap_data)
    k8s.client.CoreV1Api.return_value = api_instance
    k8s.config.load_incluster_config = MagicMock()
    return k8s


def _budget_with_k8s(
    configmap_data: dict[str, str],
    extra_env: dict[str, str] | None = None,
    budget_kwargs: dict[str, Any] | None = None,
    namespace: str = "default",
) -> Any:
    """Create a Budget with K8s env vars set and a mocked CoreV1Api."""
    from shekel._budget import Budget

    k8s_mock = _make_k8s_mock(configmap_data)
    env = {
        "KUBERNETES_SERVICE_HOST": "10.0.0.1",
        "SHEKEL_BUDGET_NAME": "test-budget",
        **(extra_env or {}),
    }

    with patch.dict("os.environ", env, clear=False):
        with patch.dict(
            "sys.modules",
            {
                "kubernetes": k8s_mock,
                "kubernetes.client": k8s_mock.client,
                "kubernetes.config": k8s_mock.config,
            },
        ):
            with patch(
                "builtins.open",
                MagicMock(
                    return_value=MagicMock(
                        __enter__=MagicMock(
                            return_value=MagicMock(read=MagicMock(return_value=namespace))
                        ),
                        __exit__=MagicMock(return_value=False),
                    )
                ),
            ):
                b = Budget(**(budget_kwargs or {}))
    return b


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestK8sDetection:
    def test_no_env_vars_skips_discovery(self) -> None:
        """Without K8s env vars, Budget is created normally."""
        from shekel._budget import Budget

        with patch.dict("os.environ", {}, clear=False):
            # Remove K8s vars if present
            env = {
                k: v
                for k, v in __import__("os").environ.items()
                if k not in ("KUBERNETES_SERVICE_HOST", "SHEKEL_BUDGET_NAME")
            }
            with patch.dict("os.environ", env, clear=True):
                b = Budget(max_usd=1.00)
        assert b._paused_externally is False
        assert b._k8s_poller is None

    def test_only_service_host_skips_discovery(self) -> None:
        """KUBERNETES_SERVICE_HOST alone (no SHEKEL_BUDGET_NAME) skips K8s path."""
        import os

        from shekel._budget import Budget

        env = {k: v for k, v in os.environ.items() if k != "SHEKEL_BUDGET_NAME"}
        env["KUBERNETES_SERVICE_HOST"] = "10.0.0.1"
        with patch.dict("os.environ", env, clear=True):
            b = Budget(max_usd=1.00)
        assert b._k8s_poller is None

    def test_only_budget_name_skips_discovery(self) -> None:
        """SHEKEL_BUDGET_NAME alone (no KUBERNETES_SERVICE_HOST) skips K8s path."""
        import os

        from shekel._budget import Budget

        env = {k: v for k, v in os.environ.items() if k != "KUBERNETES_SERVICE_HOST"}
        env["SHEKEL_BUDGET_NAME"] = "test-budget"
        with patch.dict("os.environ", env, clear=True):
            b = Budget(max_usd=1.00)
        assert b._k8s_poller is None


# ---------------------------------------------------------------------------
# ConfigMap loading
# ---------------------------------------------------------------------------


class TestConfigMapLoading:
    def test_max_usd_loaded_from_configmap(self) -> None:
        b = _budget_with_k8s({"max_usd": "0.50"})
        assert b.max_usd == pytest.approx(0.50)

    def test_warn_at_loaded_from_configmap(self) -> None:
        b = _budget_with_k8s({"max_usd": "1.00", "warn_at": "0.8"})
        assert b.warn_at == pytest.approx(0.8)

    def test_max_llm_calls_loaded_from_configmap(self) -> None:
        b = _budget_with_k8s({"max_llm_calls": "10"})
        assert b.max_llm_calls == 10

    def test_fallback_loaded_from_configmap(self) -> None:
        b = _budget_with_k8s(
            {
                "max_usd": "1.00",
                "fallback_model": "gpt-4o-mini",
                "fallback_at_pct": "0.8",
            }
        )
        assert b.fallback == {"model": "gpt-4o-mini", "at_pct": pytest.approx(0.8)}

    def test_empty_configmap_leaves_budget_unchanged(self) -> None:
        b = _budget_with_k8s({})
        assert b.max_usd is None
        assert b.warn_at is None

    def test_configmap_name_uses_budget_name_env_var(self) -> None:
        """ConfigMap fetched as shekel-budget-{SHEKEL_BUDGET_NAME}."""
        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({"max_usd": "1.00"})
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "my-agent"}

        with patch.dict("os.environ", env, clear=False):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                with patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(
                                return_value=MagicMock(read=MagicMock(return_value="default"))
                            ),
                            __exit__=MagicMock(return_value=False),
                        )
                    ),
                ):
                    Budget()

        api = k8s_mock.client.CoreV1Api.return_value
        api.read_namespaced_config_map.assert_called_once_with(
            name="shekel-budget-my-agent", namespace="default"
        )


# ---------------------------------------------------------------------------
# Config priority
# ---------------------------------------------------------------------------


class TestConfigPriority:
    def test_explicit_kwarg_overrides_configmap(self) -> None:
        """Explicit max_usd=1.00 beats ConfigMap max_usd: 0.50."""
        b = _budget_with_k8s({"max_usd": "0.50"}, budget_kwargs={"max_usd": 1.00})
        assert b.max_usd == pytest.approx(1.00)

    def test_env_var_overrides_configmap(self) -> None:
        """AGENT_BUDGET_USD=2.00 beats ConfigMap max_usd: 0.50."""
        b = _budget_with_k8s(
            {"max_usd": "0.50"},
            extra_env={"AGENT_BUDGET_USD": "2.00"},
        )
        assert b.max_usd == pytest.approx(2.00)

    def test_explicit_kwarg_overrides_env_var(self) -> None:
        """Explicit kwarg beats env var."""
        b = _budget_with_k8s(
            {},
            extra_env={"AGENT_BUDGET_USD": "2.00"},
            budget_kwargs={"max_usd": 5.00},
        )
        assert b.max_usd == pytest.approx(5.00)

    def test_configmap_applied_when_no_kwarg_or_env(self) -> None:
        """ConfigMap is used when neither kwarg nor env var is set."""
        import os

        env = {k: v for k, v in os.environ.items() if k != "AGENT_BUDGET_USD"}
        b = _budget_with_k8s({"max_usd": "0.75"}, extra_env=env)
        assert b.max_usd == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Namespace resolution
# ---------------------------------------------------------------------------


class TestNamespaceResolution:
    def test_namespace_read_from_sa_file(self) -> None:
        """Namespace is read from the ServiceAccount namespace file."""
        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({})
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "b"}

        open_mock = MagicMock()
        open_mock.return_value.__enter__ = MagicMock(
            return_value=MagicMock(read=MagicMock(return_value="my-namespace"))
        )
        open_mock.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", env, clear=False):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                with patch("builtins.open", open_mock):
                    Budget()

        api = k8s_mock.client.CoreV1Api.return_value
        api.read_namespaced_config_map.assert_called_once_with(
            name="shekel-budget-b", namespace="my-namespace"
        )

    def test_shekel_budget_namespace_env_overrides_sa_file(self) -> None:
        """SHEKEL_BUDGET_NAMESPACE overrides the SA namespace file."""
        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({})
        env = {
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "SHEKEL_BUDGET_NAME": "b",
            "SHEKEL_BUDGET_NAMESPACE": "override-ns",
        }

        with patch.dict("os.environ", env, clear=False):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                Budget()

        api = k8s_mock.client.CoreV1Api.return_value
        api.read_namespaced_config_map.assert_called_once_with(
            name="shekel-budget-b", namespace="override-ns"
        )


# ---------------------------------------------------------------------------
# Kill-switch (paused flag)
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_paused_true_sets_flag(self) -> None:
        b = _budget_with_k8s({"paused": "true"})
        assert b._paused_externally is True

    def test_paused_false_does_not_set_flag(self) -> None:
        b = _budget_with_k8s({"paused": "false"})
        assert b._paused_externally is False

    def test_paused_missing_does_not_set_flag(self) -> None:
        b = _budget_with_k8s({})
        assert b._paused_externally is False

    def test_paused_budget_raises_on_record_spend(self) -> None:
        from shekel._budget import Budget
        from shekel.exceptions import BudgetPausedError

        b = Budget(max_usd=1.00)
        b._paused_externally = True

        with pytest.raises(BudgetPausedError):
            b._record_spend(0.01, "gpt-4o-mini", {"input": 10, "output": 5})

        # Paused check fires before spend is accumulated
        assert b._spent == pytest.approx(0.0)

    def test_paused_error_is_subclass_of_budget_exceeded_error(self) -> None:
        from shekel.exceptions import BudgetExceededError, BudgetPausedError

        assert issubclass(BudgetPausedError, BudgetExceededError)

    def test_limit_exceeded_is_not_paused_error(self) -> None:
        from shekel._budget import Budget
        from shekel.exceptions import BudgetExceededError, BudgetPausedError

        b = Budget(max_usd=0.01)
        with b:
            with pytest.raises(BudgetExceededError) as exc_info:
                b._record_spend(0.05, "gpt-4o", {"input": 10, "output": 5})
        assert not isinstance(exc_info.value, BudgetPausedError)

    def test_not_paused_does_not_raise_on_record_spend(self) -> None:
        from shekel._budget import Budget

        b = Budget(max_usd=1.00)
        b._paused_externally = False
        # should not raise
        b._record_spend(0.01, "gpt-4o-mini", {"input": 10, "output": 5})


# ---------------------------------------------------------------------------
# Background poll thread
# ---------------------------------------------------------------------------


class TestPollThread:
    def test_poll_thread_started_in_k8s_mode(self) -> None:
        b = _budget_with_k8s({"max_usd": "1.00"})
        assert b._k8s_poller is not None
        assert b._k8s_poller.is_alive()
        b._k8s_poller.stop()

    def test_poll_thread_is_daemon(self) -> None:
        b = _budget_with_k8s({"max_usd": "1.00"})
        assert b._k8s_poller.daemon is True
        b._k8s_poller.stop()

    def test_poll_thread_stopped_on_budget_exit(self) -> None:
        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({"max_usd": "1.00"})
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "b"}

        with patch.dict("os.environ", env, clear=False):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                with patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(
                                return_value=MagicMock(read=MagicMock(return_value="default"))
                            ),
                            __exit__=MagicMock(return_value=False),
                        )
                    ),
                ):
                    with Budget() as b:
                        poller = b._k8s_poller

        assert poller._stop_event.is_set()

    def test_poll_updates_paused_flag(self) -> None:
        """Poller sets _paused_externally when ConfigMap changes to paused=true."""
        from shekel._budget import Budget
        from shekel.integrations.kubernetes import KubernetesPoller

        b = Budget(max_usd=1.00)
        b._paused_externally = False

        k8s_mock = _make_k8s_mock({"paused": "true"})

        with patch.dict(
            "sys.modules",
            {
                "kubernetes": k8s_mock,
                "kubernetes.client": k8s_mock.client,
                "kubernetes.config": k8s_mock.config,
            },
        ):
            poller = KubernetesPoller(b, "test", "default", interval=0.01)
            poller.start()
            poller._stop_event.wait(timeout=0.5)
            poller.stop()
            poller.join(timeout=1.0)

        assert b._paused_externally is True

    def test_poll_clears_paused_flag_when_unpaused(self) -> None:
        """Poller clears _paused_externally when ConfigMap changes to paused=false."""
        from shekel._budget import Budget
        from shekel.integrations.kubernetes import KubernetesPoller

        b = Budget(max_usd=1.00)
        b._paused_externally = True

        k8s_mock = _make_k8s_mock({"paused": "false"})

        with patch.dict(
            "sys.modules",
            {
                "kubernetes": k8s_mock,
                "kubernetes.client": k8s_mock.client,
                "kubernetes.config": k8s_mock.config,
            },
        ):
            poller = KubernetesPoller(b, "test", "default", interval=0.01)
            poller.start()
            poller._stop_event.wait(timeout=0.5)
            poller.stop()
            poller.join(timeout=1.0)

        assert b._paused_externally is False


# ---------------------------------------------------------------------------
# kubernetes package absent
# ---------------------------------------------------------------------------


class TestKubernetesPackageAbsent:
    def test_missing_kubernetes_package_no_crash(self) -> None:
        """If kubernetes is not installed, Budget construction doesn't crash."""
        from shekel._budget import Budget

        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "b"}

        # Remove kubernetes from sys.modules entirely
        modules_without_k8s = {k: v for k, v in sys.modules.items() if "kubernetes" not in k}
        modules_without_k8s["kubernetes"] = None  # type: ignore[assignment]

        with patch.dict("os.environ", env, clear=False):
            with patch.dict("sys.modules", modules_without_k8s, clear=True):
                b = Budget(max_usd=1.00)

        assert b.max_usd == pytest.approx(1.00)
        assert b._k8s_poller is None

    def test_missing_kubernetes_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from shekel._budget import Budget

        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "b"}
        modules_without_k8s = {k: v for k, v in sys.modules.items() if "kubernetes" not in k}
        modules_without_k8s["kubernetes"] = None  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="shekel.integrations.kubernetes"):
            with patch.dict("os.environ", env, clear=False):
                with patch.dict("sys.modules", modules_without_k8s, clear=True):
                    Budget(max_usd=1.00)

        assert any("kubernetes" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Redis backend activation
# ---------------------------------------------------------------------------


class TestRedisBackendActivation:
    def test_redis_backend_activated_from_configmap(self) -> None:
        """ConfigMap backend=redis + REDIS_URL → RedisBackend stored on budget."""
        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock(
            {
                "backend": "redis",
                "redis_key": "shekel:default:test-budget",
            }
        )
        env = {
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "SHEKEL_BUDGET_NAME": "test-budget",
            "REDIS_URL": "redis://localhost:6379/0",
        }

        redis_backend_mock = MagicMock()
        with patch.dict("os.environ", env, clear=False):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                with patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(
                                return_value=MagicMock(read=MagicMock(return_value="default"))
                            ),
                            __exit__=MagicMock(return_value=False),
                        )
                    ),
                ):
                    with patch(
                        "shekel.backends.redis.RedisBackend", return_value=redis_backend_mock
                    ) as mock_cls:
                        b = Budget()

        mock_cls.assert_called_once_with(url="redis://localhost:6379/0")
        assert b._k8s_redis_backend is redis_backend_mock
        assert b._k8s_redis_name == "shekel:default:test-budget"

    def test_redis_backend_skipped_without_redis_url(self) -> None:
        """ConfigMap backend=redis but no REDIS_URL → no RedisBackend."""
        import os

        env_no_redis = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
        env_no_redis.update(
            {
                "KUBERNETES_SERVICE_HOST": "10.0.0.1",
                "SHEKEL_BUDGET_NAME": "test-budget",
            }
        )

        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({"backend": "redis"})

        with patch.dict("os.environ", env_no_redis, clear=True):
            with patch.dict(
                "sys.modules",
                {
                    "kubernetes": k8s_mock,
                    "kubernetes.client": k8s_mock.client,
                    "kubernetes.config": k8s_mock.config,
                },
            ):
                with patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(
                                return_value=MagicMock(read=MagicMock(return_value="default"))
                            ),
                            __exit__=MagicMock(return_value=False),
                        )
                    ),
                ):
                    b = Budget()

        assert not hasattr(b, "_k8s_redis_backend") or b._k8s_redis_backend is None


# ---------------------------------------------------------------------------
# Per-pod cap
# ---------------------------------------------------------------------------


class TestPerPodCap:
    def test_per_pod_cap_stored_as_float(self) -> None:
        b = _budget_with_k8s({"per_pod_cap": "0.25"})
        assert b._per_pod_cap_usd == pytest.approx(0.25)

    def test_per_pod_cap_does_not_recurse(self) -> None:
        # Regression for SHEK-26: constructing a Budget with per_pod_cap in the
        # ConfigMap must not trigger infinite recursion via nested Budget.__init__ calls.
        b = _budget_with_k8s({"per_pod_cap": "0.10"})
        assert b._per_pod_cap_usd == pytest.approx(0.10)
        assert not hasattr(b, "_per_pod_budget")

    def test_per_pod_cap_enforced_on_exceed(self) -> None:
        from shekel.exceptions import BudgetExceededError

        b = _budget_with_k8s({"per_pod_cap": "0.05"})
        with b:
            b._record_spend(0.03, "gpt-4o", {"input": 100, "output": 50})  # under cap — ok
            with pytest.raises(BudgetExceededError) as exc_info:
                b._record_spend(0.03, "gpt-4o", {"input": 100, "output": 50})  # exceeds cap
        assert exc_info.value.limit == pytest.approx(0.05)

    def test_per_pod_cap_not_enforced_when_absent(self) -> None:
        # No per_pod_cap in ConfigMap → spending freely past any cap value must not raise.
        b = _budget_with_k8s({})
        with b:
            b._record_spend(0.50, "gpt-4o", {"input": 100, "output": 50})
            b._record_spend(0.50, "gpt-4o", {"input": 100, "output": 50})

    def test_per_pod_cap_warn_only_does_not_raise(self) -> None:
        # SHEK-33: warn_only=True must suppress the raise even when per_pod_cap is exceeded.
        b = _budget_with_k8s({"per_pod_cap": "0.05"}, budget_kwargs={"warn_only": True})
        with b:
            b._record_spend(0.03, "gpt-4o", {"input": 10, "output": 5})
            b._record_spend(
                0.03, "gpt-4o", {"input": 10, "output": 5}
            )  # exceeds cap — must not raise
        assert b._spent == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# SHEK-27: poller/reporter restart on Budget re-entry
# ---------------------------------------------------------------------------


class TestPollerRestart:
    def test_poller_restarts_on_re_entry(self) -> None:
        # Regression for SHEK-27: re-entering a session budget must spawn a new
        # live poller thread — the old one was stopped on __exit__.
        b = _budget_with_k8s({"max_usd": "1.00"})
        with b:
            first_poller = b._k8s_poller
        first_poller.join(timeout=2.0)  # wait for thread to actually die after stop()
        assert not first_poller.is_alive()
        with b:
            assert b._k8s_poller is not first_poller
            assert b._k8s_poller.is_alive()

    def test_reporter_restarts_on_re_entry(self) -> None:
        b = _budget_with_k8s({"max_usd": "1.00", "backend": "k8s"})
        with b:
            first_reporter = b._k8s_reporter
        first_reporter.join(timeout=2.0)  # wait for thread to actually die
        assert not first_reporter.is_alive()
        with b:
            assert b._k8s_reporter is not first_reporter
            assert b._k8s_reporter.is_alive()

    def test_restart_idempotent_when_thread_alive(self) -> None:
        # Calling _restart_k8s_threads() while the thread is still alive must not
        # create a duplicate — the same instance should be kept.
        b = _budget_with_k8s({"max_usd": "1.00"})
        with b:
            poller_id = id(b._k8s_poller)
            b._restart_k8s_threads()
            assert id(b._k8s_poller) == poller_id

    def test_restart_noop_outside_k8s(self) -> None:
        from shekel._budget import Budget

        b = Budget(max_usd=1.0)
        b._restart_k8s_threads()  # must not raise
        assert b._k8s_poller is None
        assert b._k8s_reporter is None

    async def test_async_poller_restarts_on_re_entry(self) -> None:
        # Same as test_poller_restarts_on_re_entry but via async with — covers
        # __aenter__ / __aexit__ paths including _restart_k8s_threads() call.
        b = _budget_with_k8s({"max_usd": "1.00"})
        async with b:
            first_poller = b._k8s_poller
        first_poller.join(timeout=2.0)
        assert not first_poller.is_alive()
        async with b:
            assert b._k8s_poller is not first_poller
            assert b._k8s_poller.is_alive()

    def test_exit_exceeded_status_with_k8s_poller(self) -> None:
        # Exercises the "exceeded" exit-status branch in __exit__ while K8s threads are active.
        from shekel.exceptions import BudgetExceededError

        b = _budget_with_k8s({"max_usd": "0.01"})
        with pytest.raises(BudgetExceededError):
            with b:
                b._record_spend(0.02, "gpt-4o", {"input": 10, "output": 5})

    def test_exit_warned_status_with_k8s_poller(self) -> None:
        # Exercises the "warned" exit-status branch in __exit__ while K8s threads are active.
        warned = []
        b = _budget_with_k8s({"max_usd": "1.00", "warn_at": "0.5"})
        b.on_warn = lambda spent, limit: warned.append(spent)
        with b:
            b._record_spend(0.60, "gpt-4o", {"input": 10, "output": 5})


# ---------------------------------------------------------------------------
# SHEK-17 fields stored
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_configmap_fetch_error_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """CoreV1Api raising an exception logs a warning and returns None (no crash)."""
        import logging

        from shekel._budget import Budget

        k8s_mock = MagicMock()
        k8s_mock.config.load_incluster_config = MagicMock()
        k8s_mock.client.CoreV1Api.return_value.read_namespaced_config_map.side_effect = (
            RuntimeError("timeout")
        )
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "b"}

        with caplog.at_level(logging.WARNING, logger="shekel.integrations.kubernetes"):
            with patch.dict("os.environ", env, clear=False):
                with patch.dict(
                    "sys.modules",
                    {
                        "kubernetes": k8s_mock,
                        "kubernetes.client": k8s_mock.client,
                        "kubernetes.config": k8s_mock.config,
                    },
                ):
                    with patch(
                        "builtins.open",
                        MagicMock(
                            return_value=MagicMock(
                                __enter__=MagicMock(
                                    return_value=MagicMock(read=MagicMock(return_value="default"))
                                ),
                                __exit__=MagicMock(return_value=False),
                            )
                        ),
                    ):
                        b = Budget(max_usd=1.00)

        assert b.max_usd == pytest.approx(1.00)
        assert any("Failed to load ConfigMap" in r.message for r in caplog.records)

    def test_redis_import_error_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Missing redis package during backend activation logs a warning (no crash)."""
        import logging

        from shekel._budget import Budget

        k8s_mock = _make_k8s_mock({"backend": "redis"})
        env = {
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "SHEKEL_BUDGET_NAME": "b",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        modules_no_redis = {
            k: v for k, v in sys.modules.items() if not k.startswith("shekel.backends.redis")
        }
        modules_no_redis["shekel.backends.redis"] = None  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="shekel.integrations.kubernetes"):
            with patch.dict("os.environ", env, clear=False):
                with patch.dict(
                    "sys.modules",
                    {
                        **{
                            "kubernetes": k8s_mock,
                            "kubernetes.client": k8s_mock.client,
                            "kubernetes.config": k8s_mock.config,
                        },
                        **modules_no_redis,
                    },
                ):
                    with patch(
                        "builtins.open",
                        MagicMock(
                            return_value=MagicMock(
                                __enter__=MagicMock(
                                    return_value=MagicMock(read=MagicMock(return_value="default"))
                                ),
                                __exit__=MagicMock(return_value=False),
                            )
                        ),
                    ):
                        Budget(max_usd=1.00)

        assert any("redis" in r.message.lower() for r in caplog.records)

    def test_apply_k8s_config_exception_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Regression for SHEK-28: non-ImportError from apply_k8s_config must be
        # logged as a warning so operators can diagnose misconfigured ConfigMaps.
        import logging
        from unittest.mock import patch

        from shekel._budget import Budget

        with patch(
            "shekel.integrations.kubernetes.apply_k8s_config",
            side_effect=ValueError("bad value"),
        ):
            with patch.dict(
                "os.environ",
                {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "test-budget"},
            ):
                with caplog.at_level(logging.WARNING, logger="shekel._budget"):
                    Budget()

        assert any("K8s features disabled" in r.message for r in caplog.records)

    def test_apply_k8s_config_import_error_is_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # ImportError (optional dependency not installed) must remain silent.
        import logging
        from unittest.mock import patch

        from shekel._budget import Budget

        with patch(
            "shekel.integrations.kubernetes.apply_k8s_config",
            side_effect=ImportError("no module"),
        ):
            with patch.dict(
                "os.environ",
                {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "SHEKEL_BUDGET_NAME": "test-budget"},
            ):
                with caplog.at_level(logging.WARNING, logger="shekel._budget"):
                    Budget()

        assert not any("K8s features disabled" in r.message for r in caplog.records)


class TestShek17Fields:
    def test_flush_every_usd_stored(self) -> None:
        b = _budget_with_k8s({"flush_every_usd": "0.10"})
        assert b._k8s_flush_every_usd == pytest.approx(0.10)

    def test_flush_every_seconds_stored(self) -> None:
        b = _budget_with_k8s({"flush_every_seconds": "30"})
        assert b._k8s_flush_every_seconds == pytest.approx(30.0)

    def test_scope_mode_stored(self) -> None:
        b = _budget_with_k8s({"scope_mode": "shared"})
        assert b._k8s_scope_mode == "shared"

    def test_scope_group_by_stored(self) -> None:
        b = _budget_with_k8s({"scope_group_by": "team"})
        assert b._k8s_scope_group_by == "team"


# ---------------------------------------------------------------------------
# SHEK-17: KubernetesSpendReporter
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _k8s_sys_modules(k8s_mock: MagicMock):  # type: ignore[return]
    with patch.dict(
        "sys.modules",
        {
            "kubernetes": k8s_mock,
            "kubernetes.client": k8s_mock.client,
            "kubernetes.config": k8s_mock.config,
        },
    ):
        yield


@contextlib.contextmanager
def _flush_env(k8s_mock: MagicMock, hostname: str = "test-pod"):  # type: ignore[return]
    with patch.dict("os.environ", {"HOSTNAME": hostname}, clear=False):
        with _k8s_sys_modules(k8s_mock):
            yield


def _make_api_exception_class(k8s_mock: MagicMock) -> type:
    class FakeApiException(Exception):
        def __init__(self, status: int = 500) -> None:
            self.status = status

    k8s_mock.client.ApiException = FakeApiException
    return FakeApiException


class TestKubernetesSpendReporter:
    # ── Activation ────────────────────────────────────────────────────────

    def test_reporter_not_started_when_backend_absent(self) -> None:
        b = _budget_with_k8s({})
        assert b._k8s_reporter is None

    def test_reporter_not_started_when_backend_redis(self) -> None:
        b = _budget_with_k8s({"backend": "redis"}, extra_env={"REDIS_URL": "redis://localhost"})
        assert b._k8s_reporter is None

    def test_reporter_started_when_backend_k8s(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"})
        assert b._k8s_reporter is not None

    def test_reporter_flush_every_seconds_from_configmap(self) -> None:
        b = _budget_with_k8s({"backend": "k8s", "flush_every_seconds": "45"})
        assert b._k8s_reporter._flush_every_seconds == pytest.approx(45.0)

    def test_reporter_flush_every_usd_from_configmap(self) -> None:
        b = _budget_with_k8s({"backend": "k8s", "flush_every_usd": "0.25"})
        assert b._k8s_reporter._flush_every_usd == pytest.approx(0.25)

    def test_reporter_flush_every_seconds_defaults_to_60(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"})
        assert b._k8s_reporter._flush_every_seconds == pytest.approx(60.0)

    def test_reporter_group_value_from_env(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"}, extra_env={"SHEKEL_GROUP_VALUE": "team-a"})
        assert b._k8s_reporter._group_value == "team-a"

    def test_reporter_group_value_empty_by_default(self) -> None:
        import os

        env = {k: v for k, v in os.environ.items() if k != "SHEKEL_GROUP_VALUE"}
        b = _budget_with_k8s({"backend": "k8s"}, extra_env=env)
        assert b._k8s_reporter._group_value == ""

    # ── Spend accumulation ─────────────────────────────────────────────────

    def test_on_spend_accumulates_total_spent(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        r.on_spend(0.10)
        r.on_spend(0.25)
        assert r._total_spent == pytest.approx(0.35)

    def test_on_spend_accumulates_total_calls(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        r.on_spend(0.10)
        r.on_spend(0.20)
        assert r._total_calls == 2

    def test_on_spend_no_flush_when_no_usd_threshold(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=None)
        with patch.object(r, "_flush") as mock_flush:
            r.on_spend(999.99)
        mock_flush.assert_not_called()

    # ── USD threshold ──────────────────────────────────────────────────────

    def test_usd_threshold_triggers_flush(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=0.10)
        with patch.object(r, "_flush") as mock_flush:
            r.on_spend(0.11)
        mock_flush.assert_called_once()

    def test_usd_threshold_not_triggered_below_threshold(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=1.00)
        with patch.object(r, "_flush") as mock_flush:
            r.on_spend(0.50)
        mock_flush.assert_not_called()

    def test_usd_threshold_exact_boundary_triggers_flush(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=0.10)
        with patch.object(r, "_flush") as mock_flush:
            r.on_spend(0.10)
        mock_flush.assert_called_once()

    def test_usd_threshold_delta_uses_last_flush_as_baseline(self) -> None:
        """Delta is relative to _last_flush_spent, not zero."""
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=0.50)
        r._last_flush_spent = 0.40
        r._total_spent = 0.40

        with patch.object(r, "_flush") as mock_flush:
            r.on_spend(0.45)  # total=0.85, delta=0.45 — below 0.50
            mock_flush.assert_not_called()
            r.on_spend(0.10)  # total=0.95, delta=0.55 — above 0.50
            mock_flush.assert_called_once()

    # ── Background flush thread ────────────────────────────────────────────

    def test_run_calls_flush_on_interval(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_seconds=60.0)
        flush_calls = [0]
        r._flush = lambda: flush_calls.__setitem__(0, flush_calls[0] + 1)  # type: ignore[assignment]

        with patch.object(r._stop_event, "wait", side_effect=iter([False, True])):
            r.run()

        assert flush_calls[0] == 1

    def test_run_passes_interval_to_wait(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_seconds=30.0)
        r._flush = MagicMock()  # type: ignore[assignment]

        with patch.object(r._stop_event, "wait", side_effect=iter([True])) as mock_wait:
            r.run()

        mock_wait.assert_called_with(30.0)

    def test_run_stops_when_stop_event_set(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        r._flush = MagicMock()  # type: ignore[assignment]

        with patch.object(r._stop_event, "wait", side_effect=iter([True])):
            r.run()

        r._flush.assert_not_called()  # type: ignore[union-attr]

    # ── Exit flush ─────────────────────────────────────────────────────────

    def test_exit_flush_on_sync_context_exit(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"})
        mock_flush_stop = MagicMock()
        b._k8s_reporter.flush_and_stop = mock_flush_stop

        with patch("shekel._patch.remove_patches"):
            b.__exit__(None, None, None)

        mock_flush_stop.assert_called_once()

    def test_exit_flush_on_exception_exit(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"})
        mock_flush_stop = MagicMock()
        b._k8s_reporter.flush_and_stop = mock_flush_stop

        with patch("shekel._patch.remove_patches"):
            b.__exit__(RuntimeError, RuntimeError("boom"), None)

        mock_flush_stop.assert_called_once()

    def test_exit_flush_on_async_context_exit(self) -> None:
        import asyncio

        b = _budget_with_k8s({"backend": "k8s"})
        mock_flush_stop = MagicMock()
        b._k8s_reporter.flush_and_stop = mock_flush_stop

        async def run() -> None:
            with patch("shekel._patch.remove_patches"):
                await b.__aexit__(None, None, None)

        asyncio.run(run())
        mock_flush_stop.assert_called_once()

    def test_exit_flush_on_async_exception_exit(self) -> None:
        import asyncio

        b = _budget_with_k8s({"backend": "k8s"})
        mock_flush_stop = MagicMock()
        b._k8s_reporter.flush_and_stop = mock_flush_stop

        async def run() -> None:
            with patch("shekel._patch.remove_patches"):
                await b.__aexit__(RuntimeError, RuntimeError("async boom"), None)

        asyncio.run(run())
        mock_flush_stop.assert_called_once()

    # ── _flush() — hostname guard ──────────────────────────────────────────

    def test_flush_skipped_when_hostname_absent(self) -> None:
        import os

        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.50

        env = {k: v for k, v in os.environ.items() if k != "HOSTNAME"}
        with patch.dict("os.environ", env, clear=True):
            with _k8s_sys_modules(k8s_mock):
                r._flush()

        api = k8s_mock.client.CoreV1Api.return_value
        assert not api.patch_namespaced_config_map.called
        assert not api.create_namespaced_config_map.called

    # ── _flush() — patch-or-create logic ──────────────────────────────────

    def test_flush_patches_configmap_first(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.42
        r._total_calls = 3

        with _flush_env(k8s_mock, hostname="my-pod"):
            r._flush()

        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.assert_called_once()
        api.create_namespaced_config_map.assert_not_called()

    def test_flush_creates_on_404(self) -> None:
        k8s_mock = _make_k8s_mock({})
        FakeApiException = _make_api_exception_class(k8s_mock)
        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.side_effect = FakeApiException(404)

        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.10

        with _flush_env(k8s_mock, hostname="my-pod"):
            r._flush()

        api.create_namespaced_config_map.assert_called_once()

    def test_flush_non_404_api_exception_logged_as_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        k8s_mock = _make_k8s_mock({})
        FakeApiException = _make_api_exception_class(k8s_mock)
        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.side_effect = FakeApiException(503)

        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.10

        with caplog.at_level(logging.WARNING, logger="shekel.integrations.kubernetes"):
            with _flush_env(k8s_mock, hostname="my-pod"):
                r._flush()  # must not raise

        assert any("Failed to flush" in rec.message for rec in caplog.records)

    def test_flush_logs_warning_on_generic_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        k8s_mock = _make_k8s_mock({})
        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.side_effect = OSError("connection refused")

        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.10

        with caplog.at_level(logging.WARNING, logger="shekel.integrations.kubernetes"):
            with _flush_env(k8s_mock, hostname="my-pod"):
                r._flush()  # must not raise

        assert any("Failed to flush" in rec.message for rec in caplog.records)

    def test_flush_does_not_raise_on_failure(self) -> None:
        k8s_mock = _make_k8s_mock({})
        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.side_effect = OSError("network error")

        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.10

        with _flush_env(k8s_mock, hostname="my-pod"):
            r._flush()  # must not raise

    # ── _flush() — ConfigMap body ──────────────────────────────────────────

    def test_flush_configmap_name_and_namespace(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("my-budget", "production")
        r._total_spent = 0.10

        with _flush_env(k8s_mock, hostname="worker-pod-7"):
            r._flush()

        api = k8s_mock.client.CoreV1Api.return_value
        args = api.patch_namespaced_config_map.call_args[0]
        assert args[0] == "shekel-spend-worker-pod-7"
        assert args[1] == "production"

    def test_flush_configmap_labels_correct(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("my-budget", "default", group_value="team-a")
        r._total_spent = 0.10

        with _flush_env(k8s_mock, hostname="pod-1"):
            r._flush()

        body = k8s_mock.client.CoreV1Api.return_value.patch_namespaced_config_map.call_args[0][2]
        labels = body["metadata"]["labels"]
        assert labels["shekel.dev/spend-report"] == "true"
        assert labels["shekel.dev/budget"] == "my-budget"
        assert labels["shekel.dev/group"] == "team-a"

    def test_flush_group_label_omitted_when_empty(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default", group_value="")
        r._total_spent = 0.10

        with _flush_env(k8s_mock, hostname="pod-1"):
            r._flush()

        body = k8s_mock.client.CoreV1Api.return_value.patch_namespaced_config_map.call_args[0][2]
        assert "shekel.dev/group" not in body["metadata"]["labels"]

    def test_flush_configmap_data_fields(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 1.23
        r._total_calls = 7

        with _flush_env(k8s_mock, hostname="test-pod"):
            r._flush()

        data = k8s_mock.client.CoreV1Api.return_value.patch_namespaced_config_map.call_args[0][2][
            "data"
        ]
        assert data["spent_usd"] == "1.23"
        assert data["call_count"] == "7"
        assert data["pod_name"] == "test-pod"
        assert "T" in data["last_updated"] and data["last_updated"].endswith("Z")

    def test_flush_writes_cumulative_total_not_delta(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._last_flush_spent = 0.50
        r._total_spent = 0.75  # delta = 0.25, but we expect cumulative 0.75
        r._total_calls = 5

        with _flush_env(k8s_mock, hostname="pod-1"):
            r._flush()

        body = k8s_mock.client.CoreV1Api.return_value.patch_namespaced_config_map.call_args[0][2]
        assert body["data"]["spent_usd"] == "0.75"

    # ── _flush() — baseline tracking ──────────────────────────────────────

    def test_flush_updates_last_flush_spent_on_success(self) -> None:
        k8s_mock = _make_k8s_mock({})
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.75
        r._total_calls = 5

        with _flush_env(k8s_mock, hostname="pod-1"):
            r._flush()

        assert r._last_flush_spent == pytest.approx(0.75)

    def test_flush_does_not_update_baseline_on_failure(self) -> None:
        """After a failed flush, _last_flush_spent is unchanged for retry with full total."""
        k8s_mock = _make_k8s_mock({})
        api = k8s_mock.client.CoreV1Api.return_value
        api.patch_namespaced_config_map.side_effect = OSError("network error")

        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "default")
        r._total_spent = 0.75
        r._last_flush_spent = 0.50

        with _flush_env(k8s_mock, hostname="pod-1"):
            r._flush()

        assert r._last_flush_spent == pytest.approx(0.50)

    # ── stop / flush_and_stop ──────────────────────────────────────────────

    def test_stop_sets_stop_event(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        assert not r._stop_event.is_set()
        r.stop()
        assert r._stop_event.is_set()

    def test_flush_and_stop_calls_flush(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        with patch.object(r, "_flush") as mock_flush:
            r.flush_and_stop()
        mock_flush.assert_called_once()

    def test_flush_and_stop_sets_stop_event(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns")
        with patch.object(r, "_flush"):
            r.flush_and_stop()
        assert r._stop_event.is_set()

    # ── Budget._record_spend integration ──────────────────────────────────

    def test_record_spend_notifies_reporter(self) -> None:
        b = _budget_with_k8s({"backend": "k8s"}, budget_kwargs={"max_usd": 10.0})
        assert b._k8s_reporter is not None

        with patch.object(b._k8s_reporter, "on_spend") as mock_on_spend:
            b._record_spend(0.05, "gpt-4", {"input": 100, "output": 50})

        mock_on_spend.assert_called_once_with(0.05)

    def test_record_spend_does_not_notify_when_no_reporter(self) -> None:
        """Budget without K8s env doesn't have a reporter — no crash."""
        import os

        from shekel._budget import Budget

        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("KUBERNETES_SERVICE_HOST", "SHEKEL_BUDGET_NAME")
        }
        with patch.dict("os.environ", env, clear=True):
            b = Budget(max_usd=10.0)

        assert b._k8s_reporter is None
        b._record_spend(0.05, "gpt-4", {"input": 100, "output": 50})  # must not raise

    # ── Budget integration ─────────────────────────────────────────────────

    def test_reporter_sees_cost_of_limit_exceeding_call(self) -> None:
        # SHEK-32: on_spend must be called before enforcement checks so the
        # reporter captures the cost of the call that triggers BudgetExceededError.
        from shekel import Budget
        from shekel.exceptions import BudgetExceededError
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        reporter = KubernetesSpendReporter("b", "ns")
        b = Budget(max_usd=0.05)
        b._k8s_reporter = reporter

        with b:
            b._record_spend(0.03, "gpt-4o", {"input": 10, "output": 5})
            with pytest.raises(BudgetExceededError):
                b._record_spend(0.03, "gpt-4o", {"input": 10, "output": 5})

        assert reporter._total_spent == pytest.approx(0.06)

    # ── Thread safety ──────────────────────────────────────────────────────

    def test_concurrent_on_spend_calls_thread_safe(self) -> None:
        from shekel.integrations.kubernetes import KubernetesSpendReporter

        r = KubernetesSpendReporter("b", "ns", flush_every_usd=None)

        def spend_batch() -> None:
            for _ in range(100):
                r.on_spend(0.01)

        threads = [threading.Thread(target=spend_batch) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert r._total_spent == pytest.approx(10.0)
        assert r._total_calls == 1000
