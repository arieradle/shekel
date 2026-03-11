# COMPREHENSIVE IMPLEMENTATION PLAN: Shekel v0.2.5 Provider Adapter Refactoring

## Executive Summary

This plan refactors Shekel's hardcoded provider logic into a pluggable `ProviderAdapter` interface. Maintains 100% backward compatibility while enabling community extensions.

**Key Outcomes:**
- OpenAI and Anthropic extracted to provider adapters
- Provider discovery registry (auto-load on import)
- Clear adapter interface with sync/async streaming support
- Complete extension documentation with Cohere example
- Zero breaking changes to public API

**Value Proposition:** Control and protect your LLM costs. One line. Zero config.

---

## 6 Phases Overview

| Phase | Task | Files | Hours | Status |
|-------|------|-------|-------|--------|
| **0** | Test Infrastructure | 2 new | 4 | Planned |
| **1** | Adapter Base Classes | 3 new | 6 | Planned |
| **2** | OpenAI Adapter | 2 new | 8 | Planned |
| **3** | Anthropic Adapter | 2 new | 8 | Planned |
| **4** | Refactor _patch.py | 1 modified | 4 | Planned |
| **5** | Documentation | 3 new | 6 | Planned |

**Total:** ~36 hours (1 week comfortable pace)

---

## PHASE 0: Test Infrastructure

**Objective:** Establish test fixtures and mock infrastructure before implementation

### Task 0.1: Create Test Base Classes
- **File:** `tests/providers/conftest.py` (NEW)
- **Purpose:** Mock response factories
- **Includes:** `ProviderTestBase` with mock OpenAI and Anthropic responses
- **Acceptance:** All existing tests pass

### Task 0.2: Create Test Directory
- **Files:** `tests/providers/` dir, `__init__.py`
- **Acceptance:** pytest discovers tests

### Task 0.3: Backup Tests
- **Action:** Document backup for regression validation
- **Acceptance:** Can restore if needed

---

## PHASE 1: Adapter Infrastructure

### Task 1.1: Create `shekel/providers/__init__.py`
```python
from shekel.providers.base import ProviderAdapter, ProviderRegistry, ADAPTER_REGISTRY
__all__ = ['ProviderAdapter', 'ProviderRegistry', 'ADAPTER_REGISTRY']
```

### Task 1.2: Create `shekel/providers/base.py`
Define ProviderAdapter ABC:
- `name` property → str
- `install_patches()` → None
- `remove_patches()` → None
- `extract_tokens(response)` → (int, int, str)
- `detect_streaming(kwargs, response)` → bool
- `wrap_stream(stream)` → Generator yielding (int, int, str) finally

Define ProviderRegistry with register(), install_all(), remove_all(), get_by_name()

Create ADAPTER_REGISTRY singleton

**Acceptance:** All abstract methods defined, type hints correct

### Task 1.3: Write Tests
- **File:** `tests/providers/test_adapters_base.py`
- **Coverage:** > 95%

---

## PHASE 2: OpenAI Adapter

### Task 2.1: Create `shekel/providers/openai.py`
Extract from _patch.py:
- `_openai_sync_wrapper` → adapter method
- `_openai_async_wrapper` → adapter method
- `_wrap_openai_stream` → `wrap_stream()`
- `_extract_openai_tokens` → `extract_tokens()`

Implement all 6 abstract methods

**Acceptance:** Behavior identical to current, type hints present

### Task 2.2: Register in `__init__.py`
Auto-register OpenAIAdapter on import

### Task 2.3: Write Tests
- **File:** `tests/providers/test_openai_adapter.py`
- **Coverage:** > 90%
- **Tests:** Token extraction, streaming, fallback, patching

---

## PHASE 3: Anthropic Adapter

### Task 3.1: Create `shekel/providers/anthropic.py`
Extract from _patch.py:
- `_anthropic_sync_wrapper` → adapter method
- `_anthropic_async_wrapper` → adapter method
- `_wrap_anthropic_stream` → `wrap_stream()` (handle message_start, message_delta events)
- `_extract_anthropic_tokens` → `extract_tokens()`

**Key difference:** Streaming detection via duck-typing (hasattr), event-based token collection

**Acceptance:** Event handling correct, behavior identical

### Task 3.2: Register in `__init__.py`
Auto-register AnthropicAdapter

### Task 3.3: Write Tests
- **File:** `tests/providers/test_anthropic_adapter.py`
- **Coverage:** > 90%
- **Tests:** Event tracking, streaming, fallback validation

---

## PHASE 4: Refactor `_patch.py`

### Task 4.1: Simplify `_install_patches()`
Replace with:
```python
def _install_patches() -> None:
    from shekel.providers import ADAPTER_REGISTRY
    for adapter in ADAPTER_REGISTRY.adapters:
        adapter.install_patches()
```

### Task 4.2: Simplify `_restore_patches()`
Replace with:
```python
def _restore_patches() -> None:
    from shekel.providers import ADAPTER_REGISTRY
    for adapter in ADAPTER_REGISTRY.adapters:
        adapter.remove_patches()
```

### Task 4.3: Remove Hardcoded Provider Code
Delete: All `_openai_*` and `_anthropic_*` functions

Keep: `_record()`, `_apply_fallback_if_needed()`, `_validate_same_provider()`

**Result:** _patch.py shrinks from 362 to ~50 lines

### Task 4.4: Validate
Run full test suite: All tests pass, no API changes

---

## PHASE 5: Documentation

### Task 5.1: Create `docs/EXTENDING.md`
**Sections:**
1. What is a ProviderAdapter?
2. Building a Custom Adapter (step-by-step walkthrough)
3. Example: Adding Cohere Adapter (template code)
4. Testing Your Adapter
5. Contributing Back

### Task 5.2: Update `README.md`
- Add "Extensibility" section
- Link to EXTENDING.md
- Message: "Shekel works with any LLM provider"

### Task 5.3: Add Code Comments
- Module docstrings on all adapters
- Method docstrings for all abstract methods
- Implementation notes for complex logic

### Task 5.4: Create `examples/cohere_adapter_template.py`
- Realistic Cohere adapter skeleton
- All 6 methods with stub implementations
- Comments explaining what to fill in

---

## Testing Strategy

### Coverage Goals
- Adapters: > 90%
- Registry: > 95%
- Total: All existing tests pass

### Test Types
- **Unit tests:** Mock responses, individual methods
- **Integration:** Existing test suite (regression)
- **Streaming:** Token accuracy from stream events
- **Fallback:** Validation and switching logic

### Regression Plan
After each phase:
```bash
pytest tests/ --cov=shekel --cov-report=html
```
- 100% pass rate required
- No API changes
- Token extraction matches current byte-for-byte

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| Breaking API changes | Medium | High | All imports identical, backwards compat tests |
| Adapter tests insufficient | Medium | High | > 90% coverage, regression tests |
| Streaming breaks | Low | High | Mock SDK responses, byte comparison |
| Fallback breaks | Low | Medium | Keep in core, validation tests |

**Rollback:** Revert to main, analyze, fix, re-test

---

## Validation Checklist

### Code Quality
- [ ] All adapters implement ProviderAdapter interface
- [ ] Type hints on all public methods
- [ ] No linting errors
- [ ] Code review approved

### Testing
- [ ] All existing tests pass (100%)
- [ ] All new tests pass (100%)
- [ ] Coverage > 90%
- [ ] Regression tests validate behavior

### Backwards Compatibility
- [ ] No breaking API changes
- [ ] All imports work identically
- [ ] User code needs zero changes

### Documentation
- [ ] EXTENDING.md complete
- [ ] README updated
- [ ] All code has docstrings
- [ ] Cohere template provided

### Release
- [ ] CHANGELOG updated
- [ ] Version bumped to v0.2.5
- [ ] CI/CD passes
- [ ] Release notes prepared

---

## Timeline

### Critical Path
Phase 0 → Phase 1 → (Phase 2 + 3 parallel) → Phase 4 → Phase 5

### Recommended Schedule
- **Day 1 (4 hrs):** Phase 0 + Phase 1 — Test infrastructure
- **Days 2-3 (8 hrs):** Phase 2 + Phase 3 — Extract adapters (parallel)
- **Day 4 (4 hrs):** Phase 4 — Simplify _patch.py
- **Day 5 (6 hrs):** Phase 5 — Documentation

**Total:** ~36 hours (8 hrs/day comfortable)

---

## Success Criteria

✅ All 6 phases completed
✅ Zero breaking changes to public API
✅ > 90% test coverage on adapters
✅ All existing tests pass (100%)
✅ Streaming behavior identical to current
✅ Token extraction behavior identical
✅ EXTENDING.md complete
✅ Feature branch ready to merge
✅ v0.2.5 release ready

---

**STATUS: PLANNING COMPLETE — READY FOR REVIEW**

**NOT YET EXECUTED**

Date: 2026-03-11
Version: Shekel v0.2.5
Branch: feat/provider-adapter-refactoring
