"""Kubernetes in-cluster auto-discovery and spend reporting for shekel (SHEK-16/17).

When both KUBERNETES_SERVICE_HOST and SHEKEL_BUDGET_NAME are set, Budget.__init__
loads its configuration from the ConfigMap shekel-budget-{name} in the pod's
namespace. A background daemon thread polls the ConfigMap's paused key at
SHEKEL_POLL_INTERVAL_SECONDS (default 10) to implement the kill-switch.

When ConfigMap has backend=k8s, a KubernetesSpendReporter daemon thread
periodically writes cumulative LLM spend to a shekel-spend-{pod} ConfigMap so
the controller can aggregate across pods.

Config priority (lowest → highest): ConfigMap < env var < explicit kwarg.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shekel._budget import Budget

logger = logging.getLogger(__name__)

_SA_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def is_k8s_environment() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST") and os.environ.get("SHEKEL_BUDGET_NAME"))


def _read_namespace() -> str:
    ns = os.environ.get("SHEKEL_BUDGET_NAMESPACE")
    if ns:
        return ns
    try:
        with open(_SA_NAMESPACE_FILE) as f:
            return f.read().strip()
    except OSError:
        return "default"


def _fetch_configmap(budget_name: str, namespace: str) -> dict[str, str] | None:
    try:
        import kubernetes
    except ImportError:
        logger.warning(
            "shekel[k8s]: 'kubernetes' package not installed — skipping K8s config discovery."
            " Install with: pip install shekel[k8s]"
        )
        return None

    try:
        kubernetes.config.load_incluster_config()
        v1 = kubernetes.client.CoreV1Api()
        cm = v1.read_namespaced_config_map(
            name=f"shekel-budget-{budget_name}",
            namespace=namespace,
        )
        return dict(cm.data or {})
    except Exception as exc:
        logger.warning("shekel[k8s]: Failed to load ConfigMap for %r: %s", budget_name, exc)
        return None


def _read_pod_group_value(scope_group_by: str, namespace: str) -> str:
    """Read the pod's label named *scope_group_by* and return its value."""
    pod_name = os.environ.get("HOSTNAME", "")
    if not pod_name:
        return ""
    try:
        import kubernetes  # noqa: PLC0415

        kubernetes.config.load_incluster_config()
        v1 = kubernetes.client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return str((pod.metadata.labels or {}).get(scope_group_by, ""))
    except Exception as exc:
        logger.warning(
            "shekel[k8s]: Failed to read pod label %r for scope_group_by: %s",
            scope_group_by,
            exc,
        )
        return ""


def apply_k8s_config(budget: Budget) -> None:
    """Load K8s ConfigMap and apply values to *budget* (mutates in place).

    Called at the end of Budget.__init__. Only fills fields that are still
    None — explicit kwargs and env vars take precedence.
    """
    if not is_k8s_environment():
        return

    budget_name = os.environ["SHEKEL_BUDGET_NAME"]
    namespace = _read_namespace()
    budget._k8s_budget_name = budget_name
    budget._k8s_namespace = namespace
    cm = _fetch_configmap(budget_name, namespace)

    if cm is None:
        return

    # --- Kill-switch (immediate, before poll thread starts) ---
    if cm.get("paused") == "true":
        budget._paused_externally = True

    # --- max_usd: env var > ConfigMap ---
    if budget.max_usd is None:
        env_val = os.environ.get("AGENT_BUDGET_USD")
        if env_val:
            budget.max_usd = float(env_val)
        elif "max_usd" in cm:
            budget.max_usd = float(cm["max_usd"])

    # --- warn_at ---
    if budget.warn_at is None and "warn_at" in cm:
        budget.warn_at = float(cm["warn_at"])

    # --- max_llm_calls ---
    if budget.max_llm_calls is None and "max_llm_calls" in cm:
        budget.max_llm_calls = int(cm["max_llm_calls"])

    # --- fallback ---
    if budget.fallback is None and "fallback_model" in cm and "fallback_at_pct" in cm:
        budget.fallback = {
            "model": cm["fallback_model"],
            "at_pct": float(cm["fallback_at_pct"]),
        }

    # --- per_pod_cap ---
    if "per_pod_cap" in cm:
        budget._per_pod_cap_usd = float(cm["per_pod_cap"])

    # --- Scope resolution (SHEK-34): must run before Redis key construction ---
    scope_group_by = cm.get("scope_group_by")
    scope_mode = cm.get("scope_mode")
    budget._k8s_scope_group_by = scope_group_by
    budget._k8s_scope_mode = scope_mode
    # env var takes priority over pod-label discovery (ConfigMap < env var pattern)
    group_value = os.environ.get("SHEKEL_GROUP_VALUE", "")
    if not group_value and scope_group_by:
        group_value = _read_pod_group_value(scope_group_by, namespace)
    budget._k8s_group_value = group_value

    # --- Redis backend ---
    if cm.get("backend") == "redis":
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                from shekel.backends.redis import RedisBackend  # noqa: PLC0415

                budget._k8s_redis_backend = RedisBackend(url=redis_url)
                # Default key is per-pod; scope_mode=shared promotes it to a group key
                budget._k8s_redis_name = cm.get("redis_key", f"shekel:{namespace}:{budget_name}")
                budget._k8s_redis_window_seconds = float(cm.get("redis_window_seconds", "86400"))
                if scope_mode == "shared" and "redis_key" not in cm:
                    if budget._k8s_group_value:
                        budget._k8s_redis_name = (
                            f"shekel:{namespace}:{budget_name}:{budget._k8s_group_value}"
                        )
                    else:
                        logger.warning(
                            "shekel[k8s]: scope_mode=shared requires scope_group_by with a "
                            "resolvable pod label or SHEKEL_GROUP_VALUE; "
                            "falling back to per-pod Redis key."
                        )
            except ImportError:
                logger.warning(
                    "shekel[k8s]: 'redis' package not installed — skipping Redis backend."
                )

    # --- SHEK-17 fields (stored for spend reporter) ---
    budget._k8s_flush_every_usd = float(cm["flush_every_usd"]) if "flush_every_usd" in cm else None
    budget._k8s_flush_every_seconds = (
        float(cm["flush_every_seconds"]) if "flush_every_seconds" in cm else None
    )

    # --- SHEK-17: Spend reporter (only when backend=k8s) ---
    if cm.get("backend") == "k8s":
        reporter = KubernetesSpendReporter(
            budget_name=budget_name,
            namespace=namespace,
            flush_every_seconds=budget._k8s_flush_every_seconds or 60.0,
            flush_every_usd=budget._k8s_flush_every_usd,
            group_value=budget._k8s_group_value,
        )
        reporter.start()
        budget._k8s_reporter = reporter

    # --- Start background kill-switch poller ---
    interval = float(os.environ.get("SHEKEL_POLL_INTERVAL_SECONDS", "10"))
    budget._k8s_poll_interval = interval
    poller = KubernetesPoller(budget, budget_name, namespace, interval)
    poller.start()
    budget._k8s_poller = poller


class KubernetesPoller(threading.Thread):
    """Daemon thread that polls the ConfigMap's *paused* key.

    Sets budget._paused_externally so the next LLM call raises BudgetExceededError
    within one poll interval of the operator setting paused=true.
    """

    def __init__(
        self,
        budget: Budget,
        budget_name: str,
        namespace: str,
        interval: float,
    ) -> None:
        super().__init__(daemon=True, name=f"shekel-k8s-poller-{budget_name}")
        self._budget = budget
        self._budget_name = budget_name
        self._namespace = namespace
        self._interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            cm = _fetch_configmap(self._budget_name, self._namespace)
            if cm is not None:
                self._budget._paused_externally = cm.get("paused") == "true"


class KubernetesSpendReporter(threading.Thread):
    """Daemon thread that flushes cumulative LLM spend to a Spend Report ConfigMap.

    Active when ConfigMap has backend=k8s. The controller reads spent_usd from
    each pod's ConfigMap and aggregates across pods — no Redis required.

    Flush triggers (whichever fires first):
    - flush_every_seconds elapsed since last flush (time-based)
    - flush_every_usd accumulated since last flush (USD threshold)
    - Budget.__exit__ / __aexit__ (always on context exit, including on exception)
    """

    def __init__(
        self,
        budget_name: str,
        namespace: str,
        flush_every_seconds: float = 60.0,
        flush_every_usd: float | None = None,
        group_value: str = "",
    ) -> None:
        super().__init__(daemon=True, name=f"shekel-k8s-reporter-{budget_name}")
        self._budget_name = budget_name
        self._namespace = namespace
        self._flush_every_seconds = flush_every_seconds
        self._flush_every_usd = flush_every_usd
        self._group_value = group_value
        self._lock = threading.Lock()
        self._total_spent: float = 0.0
        self._total_calls: int = 0
        self._last_flush_spent: float = 0.0
        self._stop_event = threading.Event()

    def on_spend(self, cost: float) -> None:
        """Called from Budget._record_spend after each LLM call."""
        with self._lock:
            self._total_spent += cost
            self._total_calls += 1
            delta = self._total_spent - self._last_flush_spent
        if self._flush_every_usd is not None and delta >= self._flush_every_usd:
            self._flush()

    def stop(self) -> None:
        self._stop_event.set()

    def flush_and_stop(self) -> None:
        """Stop the background thread and perform a final synchronous flush."""
        self._stop_event.set()
        self._flush()

    def run(self) -> None:
        while not self._stop_event.wait(self._flush_every_seconds):
            self._flush()

    def _flush(self) -> None:
        pod_name = os.environ.get("HOSTNAME")
        if not pod_name:
            return

        try:
            import kubernetes  # noqa: PLC0415
        except ImportError:  # pragma: no cover — optional dependency
            return

        with self._lock:
            total_spent = self._total_spent
            total_calls = self._total_calls

        cm_name = f"shekel-spend-{pod_name}"
        labels: dict[str, str] = {
            "shekel.dev/spend-report": "true",
            "shekel.dev/budget": self._budget_name,
        }
        if self._group_value:
            labels["shekel.dev/group"] = self._group_value

        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": cm_name,
                "namespace": self._namespace,
                "labels": labels,
            },
            "data": {
                "spent_usd": str(total_spent),
                "call_count": str(total_calls),
                "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pod_name": pod_name,
            },
        }

        success = False
        try:
            kubernetes.config.load_incluster_config()
            v1 = kubernetes.client.CoreV1Api()
            try:
                v1.patch_namespaced_config_map(cm_name, self._namespace, body)
            except kubernetes.client.ApiException as exc:
                if exc.status == 404:
                    v1.create_namespaced_config_map(self._namespace, body)
                else:
                    raise
            success = True
        except Exception as exc:
            logger.warning("shekel[k8s]: Failed to flush spend report: %s", exc)

        if success:
            with self._lock:
                self._last_flush_spent = total_spent
