"""Kubernetes in-cluster auto-discovery for shekel budget configuration (SHEK-16).

When both KUBERNETES_SERVICE_HOST and SHEKEL_BUDGET_NAME are set, Budget.__init__
loads its configuration from the ConfigMap shekel-budget-{name} in the pod's
namespace. A background daemon thread polls the ConfigMap's paused key at
SHEKEL_POLL_INTERVAL_SECONDS (default 10) to implement the kill-switch.

Config priority (lowest → highest): ConfigMap < env var < explicit kwarg.
"""

from __future__ import annotations

import logging
import os
import threading
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


def apply_k8s_config(budget: Budget) -> None:
    """Load K8s ConfigMap and apply values to *budget* (mutates in place).

    Called at the end of Budget.__init__. Only fills fields that are still
    None — explicit kwargs and env vars take precedence.
    """
    if not is_k8s_environment():
        return

    budget_name = os.environ["SHEKEL_BUDGET_NAME"]
    namespace = _read_namespace()
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
        from shekel._budget import Budget as _Budget  # noqa: PLC0415

        budget._per_pod_budget = _Budget(max_usd=float(cm["per_pod_cap"]))

    # --- Redis backend ---
    if cm.get("backend") == "redis":
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                from shekel.backends.redis import RedisBackend  # noqa: PLC0415

                budget._k8s_redis_backend = RedisBackend(url=redis_url)
                budget._k8s_redis_name = cm.get("redis_key", f"shekel:{namespace}:{budget_name}")
            except ImportError:
                logger.warning(
                    "shekel[k8s]: 'redis' package not installed — skipping Redis backend."
                )

    # --- SHEK-17 fields (stored for spend reporter) ---
    budget._k8s_flush_every_usd = float(cm["flush_every_usd"]) if "flush_every_usd" in cm else None
    budget._k8s_flush_every_seconds = (
        float(cm["flush_every_seconds"]) if "flush_every_seconds" in cm else None
    )
    budget._k8s_scope_mode = cm.get("scope_mode")
    budget._k8s_scope_group_by = cm.get("scope_group_by")

    # --- Start background kill-switch poller ---
    interval = float(os.environ.get("SHEKEL_POLL_INTERVAL_SECONDS", "10"))
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
