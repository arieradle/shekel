"""Tests for SHEK-16: in-cluster Kubernetes auto-discovery from ConfigMap.

All tests mock kubernetes.client.CoreV1Api — no live cluster required.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        from shekel.exceptions import BudgetExceededError

        b = Budget(max_usd=1.00)
        b._paused_externally = True

        with pytest.raises(BudgetExceededError):
            b._record_spend(0.01, "gpt-4o-mini", {"input": 10, "output": 5})

        # Paused check fires before spend is accumulated
        assert b._spent == pytest.approx(0.0)

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
    def test_per_pod_cap_stored_on_budget(self) -> None:
        b = _budget_with_k8s({"per_pod_cap": "0.25"})
        assert hasattr(b, "_per_pod_budget")
        assert b._per_pod_budget.max_usd == pytest.approx(0.25)


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
