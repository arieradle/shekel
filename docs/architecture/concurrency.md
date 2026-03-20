---
title: Concurrency & Thread Safety – Shekel LLM Budget Control
description: How shekel achieves thread safety and async safety: ContextVar isolation per thread and asyncio task, ref-counted patching with locks, and persistent budget caveats.
tags:
  - architecture
  - internals
  - production-ai
---

# Concurrency & Safety

- **ContextVar**: Each thread or asyncio task has its own active budget; concurrent `with budget():` in different threads/tasks do not share state.
- **Ref-counted patching**: Safe for nested contexts; patches are installed once and restored when the last context exits. A lock in `_patch` protects the refcount.
- **Persistent/session budgets**: Reused across multiple `with` blocks; not thread-safe if shared across threads. Prefer one budget per thread/task.
- **Temporal InMemoryBackend**: Not thread-safe; use one temporal budget per thread/task or a custom backend with locking for shared state.
