"""Performance test suite for Shekel provider adapters.

Organized by domain:
- test_registry_performance: Registry initialization, resolution, caching
- test_adapter_lifecycle_performance: Adapter creation, patch installation/removal
- test_message_operations_performance: Token extraction, streaming detection, wrapping
- test_error_handling_performance: Exception handling and error paths
- test_memory_performance: Memory footprint, allocation, GC behavior
- test_concurrency_performance: Thread safety, concurrent operations, scaling
"""
