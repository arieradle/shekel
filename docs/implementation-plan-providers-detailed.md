# Shekel Providers — Detailed Execution Plan (Team Instructions)

**Prepared by:** Bob (SM), Amelia (Dev), Quinn (QA), Barry (Quick Flow)  
**Source:** Implementation plan 2026-03-12 + brainstorm prioritized list  
**Scope:** Phase 1 (LiteLLM) as the reference flow; Phases 2–6 follow the same pattern.  
**Version:** 0.2.6

---

## 1. Branch and repo hygiene (Bob)

### 1.1 Branch strategy

- **One feature branch per phase** (or per provider if you split Phase 1 into smaller PRs).
- Naming: `feat/litellm-adapter`, `feat/langgraph-integration`, etc.
- Base: always latest `main`. Rebase or merge main into your branch before opening PR.

### 1.2 Open branch — instructions

```bash
# Ensure you're on main and up to date
git checkout main
git pull origin main

# Create and switch to feature branch (Phase 1 example)
git checkout -b feat/litellm-adapter
```

### 1.3 Definition of done (per phase)

- [ ] All new/updated tests pass (unit + integration as defined below).
- [ ] No new linter errors; existing tests unchanged (no regressions).
- [ ] Code follows existing patterns (`providers/*.py`, `_patch.py`).
- [ ] Optional extra in `pyproject.toml` (and `default` extra if Phase 1).
- [ ] Adapter registered in `shekel/providers/__init__.py` behind import guard (optional deps).
- [ ] PR description links to this plan and lists AC.

### 1.4 Checklist before PR

- [ ] `pytest tests/ -v` (or scope to `tests/providers` + `tests/test_patching.py`).
- [ ] `ruff check shekel tests` (or project linter).
- [ ] Manual smoke: `pip install -e ".[litellm]"` (or relevant extra), run one script inside `with budget(max_usd=1.0): litellm.completion(...)`.

---

## 2. TDD cycle (Amelia)

**Rule:** Tests first. No production code in `shekel/providers/litellm.py` or `_patch.py` LiteLLM wrappers until the test that demands it is written and failing.

### 2.1 Red–Green–Refactor loop

1. **Red:** Write a failing test (or unskip a skipped one).
2. **Green:** Minimal code in shekel to make it pass.
3. **Refactor:** Clean up; tests must stay green.

### 2.2 Phase 1 — LiteLLM: test order and locations

Tests live under `tests/providers/` and optionally `tests/test_patching.py` / `tests/integrations/`. Use `tests/providers/conftest.py` and extend with LiteLLM mocks.

| Step | Test (file + description) | What it asserts | Then implement |
|------|----------------------------|-----------------|----------------|
| 1 | `tests/providers/test_litellm_adapter.py` — `test_name_is_litellm` | `LiteLLMAdapter().name == "litellm"` | `shekel/providers/litellm.py` with class and `name`. |
| 2 | Same file — `test_implements_provider_adapter` | `isinstance(LiteLLMAdapter(), ProviderAdapter)` | Full adapter class with all abstract methods (stub or minimal). |
| 3 | Same file — `test_extract_tokens_from_valid_response` | Given mock LiteLLM response (usage.prompt_tokens, usage.completion_tokens, model), `extract_tokens` returns (in, out, model). | `extract_tokens()` in adapter. |
| 4 | Same file — `test_extract_tokens_handles_none_usage`, `test_extract_tokens_handles_missing_usage` | Return (0, 0, model) or (0, 0, "unknown"); no raise. | Defensive handling in `extract_tokens`. |
| 5 | Same file — `test_detect_streaming` | `detect_streaming(kwargs, response)` True when `kwargs.get("stream") is True`. | `detect_streaming()` in adapter. |
| 6 | Same file — `test_wrap_stream_yields_chunks_and_returns_usage` | Wrap a mock stream; iterate; get (it, ot, model) from generator return. | `wrap_stream()` in adapter. |
| 7 | Same file — `test_install_patches_stores_originals`, `test_remove_patches_restores_originals` | After install, `litellm.completion` is wrapped; after remove, original is back. Use `unittest.mock.patch` or import and compare. | `install_patches()` / `remove_patches()` in adapter (store in `_patch._originals`). |
| 8 | `tests/test_patching.py` (or new `tests/providers/test_litellm_patching.py`) — `test_litellm_completion_records_cost` | With `budget(max_usd=1.0)`, mock `litellm.completion` to return a response with usage; assert `budget.spent` updated (e.g. > 0 or specific value). | `_patch.py`: `_litellm_sync_wrapper`, `_litellm_async_wrapper`; call original, extract tokens, `_record()`. |
| 9 | Same — `test_litellm_completion_stream_records_cost` | Same but `stream=True`; mock stream with usage in last chunk; assert spend recorded. | Stream branch in sync/async wrappers; `stream_options={"include_usage": True}`; collect usage in finally and `_record`. |
| 10 | (Optional) `tests/integrations/test_litellm_integration.py` | Real `litellm.completion` call (env API key); inside `with budget()`; assert `b.spent` > 0. | No extra prod code; confirms E2E. |

### 2.3 Test file and mock pattern (Quinn)

- **New file:** `tests/providers/test_litellm_adapter.py`.
- **Base class:** Inherit from `ProviderTestBase` in `tests/providers/conftest.py`.
- **LiteLLM mocks:** Add to `conftest.py` (or in test file):
  - `MockLiteLLMResponse(model, prompt_tokens, completion_tokens)` with `.usage.prompt_tokens`, `.usage.completion_tokens`, `.model`.
  - `make_litellm_response(model, input_tokens, output_tokens)` and, if needed, `make_litellm_stream(...)` for streaming tests.
- **Patch point:** Use `unittest.mock.patch("litellm.completion", ...)` and `patch("litellm.acompletion", ...)` so tests don't call real API. Guard tests with `pytest.importorskip("litellm")` if you want them skipped when litellm is not installed.

### 2.4 Run commands (copy-paste)

```bash
# Run all provider tests
pytest tests/providers/ -v

# Run only LiteLLM adapter tests (after adding the file)
pytest tests/providers/test_litellm_adapter.py -v

# Run patching tests (including new LiteLLM ones)
pytest tests/test_patching.py -v

# Run full test suite (no integrations that need API keys)
pytest tests/ -v --ignore=tests/integrations/ -x
```

---

## 3. Step-by-step implementation instructions (Phase 1 — LiteLLM)

### 3.1 Before writing code

1. Open branch: `git checkout -b feat/litellm-adapter` (see 1.2).
2. Add optional extra to `pyproject.toml`:  
   `litellm = ["litellm>=1.0.0"]` (pin a minimum version you support).  
   Add `default = ["openai>=1.0.0", "anthropic>=0.7.0", "litellm>=1.0.0"]` if you want a default bundle.
3. Create `tests/providers/conftest.py` additions: `MockLiteLLMResponse`, `make_litellm_response` (and stream helper if needed).

### 3.2 TDD steps (in order)

1. **Adapter skeleton**  
   - Write `test_name_is_litellm` and `test_implements_provider_adapter`.  
   - Create `shekel/providers/litellm.py` with `LiteLLMAdapter`, `name = "litellm"`, and stubs for `install_patches`, `remove_patches`, `extract_tokens`, `detect_streaming`, `wrap_stream`.  
   - Green: make tests pass (e.g. return (0,0,"unknown") for extract_tokens, False for detect_streaming, etc.).

2. **Token extraction**  
   - Write `test_extract_tokens_from_valid_response` and the "handles None/missing" tests using `make_litellm_response`.  
   - Implement `extract_tokens()`: read `response.usage.prompt_tokens`, `response.usage.completion_tokens`, `response.model` (support both object and dict-like if LiteLLM can return dict). Return (0, 0, "unknown") on any error.

3. **Stream detection and stream wrapping**  
   - Write `test_detect_streaming` and `test_wrap_stream_yields_chunks_and_returns_usage`.  
   - Implement `detect_streaming(kwargs, response)` → `kwargs.get("stream") is True`.  
   - Implement `wrap_stream(stream)`: iterate stream, yield chunks, collect usage from chunks (e.g. last chunk with usage); return (it, ot, model).

4. **Install/remove patches**  
   - Write `test_install_patches_stores_originals` and `test_remove_patches_restores_originals`.  
   - In `install_patches()`: import `litellm`, store `litellm.completion` and `litellm.acompletion` in `_patch._originals["litellm_sync"]` and `_patch._originals["litellm_async"]`, then assign `litellm.completion = _patch._litellm_sync_wrapper` and `litellm.acompletion = _patch._litellm_async_wrapper`.  
   - In `remove_patches()`: restore from `_originals` and remove keys. Use try/except ImportError so missing litellm doesn't break.

5. **Wrappers in _patch.py**  
   - Write `test_litellm_completion_records_cost`: with `with budget(max_usd=1.0)`, patch `litellm.completion` to return a mock response with usage; after the call, assert `b.spent` reflects cost (or at least that _record was called).  
   - Add `_litellm_sync_wrapper(*args, **kwargs)`: get original from `_originals["litellm_sync"]`; call it; if not stream, get (it, ot, model) from response (use adapter's extract_tokens or inline same logic), call `_record(it, ot, model)`; return response.  
   - For stream: set `kwargs.setdefault("stream_options", {})["include_usage"] = True`, call original, wrap returned stream so that in a `finally` you collect usage from the stream and call `_record`.  
   - Repeat for async: `_litellm_async_wrapper`, `_wrap_litellm_stream_async`.

6. **Registration**  
   - In `shekel/providers/__init__.py`:  
     `try:`  
     `    from shekel.providers.litellm import LiteLLMAdapter`  
     `    ADAPTER_REGISTRY.register(LiteLLMAdapter())`  
     `except ImportError:`  
     `    pass`  
   - Add `LiteLLMAdapter` to `__all__` if you export it.  
   - Run full provider + patching tests; ensure no regression for OpenAI/Anthropic.

7. **Fallback (v1)**  
   - Per implementation plan: skip LiteLLM fallback rewrite in v1 (or add `_validate_same_provider` / `_apply_fallback_if_needed` branch for litellm if you want). Document in docstring or PR.

8. **Pricing**  
   - If LiteLLM returns model names with a prefix (e.g. `openai/gpt-4o`), either strip prefix before `_record` or rely on `_pricing` prefix lookup / tokencost. Add a test that records cost for a known model and assert `b.spent > 0` if you have pricing for that model.

### 3.3 Files to create or touch

| File | Action |
|------|--------|
| `shekel/providers/litellm.py` | Create. LiteLLMAdapter. |
| `shekel/_patch.py` | Add _litellm_sync_wrapper, _litellm_async_wrapper, _wrap_litellm_stream, _wrap_litellm_stream_async; _originals keys litellm_sync, litellm_async. |
| `shekel/providers/__init__.py` | try/except register LiteLLMAdapter; __all__. |
| `pyproject.toml` | litellm extra; default extra (optional). |
| `tests/providers/conftest.py` | MockLiteLLMResponse, make_litellm_response (and stream). |
| `tests/providers/test_litellm_adapter.py` | Create. All adapter unit tests. |
| `tests/test_patching.py` or `tests/providers/test_litellm_patching.py` | Add tests for "litellm.completion records cost" (sync + stream). |

---

## 4. Phases 2–6 (short instructions)

- **Branch:** `feat/langgraph-integration`, `feat/langchain-integration`, etc.
- **TDD:** Tests first for any new public API (e.g. `budgeted_invoke`). For "helper only" integrations, one test that "with budget(): framework.run() records cost" may be enough (existing OpenAI/Anthropic patches do the work).
- **Phase 2 (LangGraph):** Optional helper in `shekel/integrations/langgraph.py`; extra `langgraph`; doc update. No new adapter.
- **Phase 3 (LangChain):** Same; `shekel/integrations/langchain.py`; extra `langchain`.
- **Phase 4 (CrewAI):** Same; `shekel/integrations/crewai.py`; extra `crewai`.
- **Phase 5 (Gemini):** Either "LiteLLM only" (doc) or new adapter + _patch wrappers (same TDD pattern as LiteLLM).
- **Phase 6 (Cohere, Ollama, vLLM):** Same adapter + _patch pattern as Phase 1; each has its own branch and test file.

---

## 5. Summary checklist (Bob)

- [ ] Branch from `main`: `feat/<scope>`.
- [ ] TDD: tests first, red–green–refactor; tests in `tests/providers/` and patching tests as above.
- [ ] All tests pass; linter clean; no regression.
- [ ] Optional extra(s) in pyproject; adapter registered with import guard.
- [ ] PR with AC and link to this plan.
- [ ] Smoke test: install with extra, run one budgeted call.

---

**Document version:** 1.0  
**Date:** 2026-03-12  
**Version:** 0.2.6
