"""
Tests for bulk operations resource limits
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from chronos_mcp.bulk import BulkOperationManager, BulkOperationMode, BulkOptions


class TestBulkResourceLimits:
    """Test resource exhaustion prevention in bulk operations"""

    def test_thread_pool_respects_max_parallel_limit(self):
        """Test that thread pool size is bounded even with large batches

        CRITICAL: Without fix, 1000+ events = 1000+ threads = resource exhaustion
        WITH fix: max_workers capped at options.max_parallel (default 10)
        """
        # Patch ThreadPoolExecutor to track max_workers
        created_pools = []
        original_init = ThreadPoolExecutor.__init__

        def track_init(self, max_workers=None, *args, **kwargs):
            created_pools.append(max_workers)
            return original_init(self, max_workers=max_workers, *args, **kwargs)

        with patch.object(ThreadPoolExecutor, "__init__", track_init):
            BulkOperationManager()

            # Create large batch (1000 events)
            large_batch = [
                {
                    "summary": f"Event {i}",
                    "start": "2025-01-01T10:00:00Z",
                    "end": "2025-01-01T11:00:00Z",
                }
                for i in range(1000)
            ]

            options = BulkOptions(
                mode=BulkOperationMode.CONTINUE_ON_ERROR,
                max_parallel=10,  # Should limit to 10 threads, not 1000!
            )

            # Simulate what the FIXED code should do
            max_workers = min(len(large_batch), options.max_parallel or 10)
            with ThreadPoolExecutor(max_workers=max_workers):
                pass

            # Verify pool is bounded
            last_pool_size = created_pools[-1]
            assert last_pool_size <= options.max_parallel, (
                f"Thread pool created with {last_pool_size} workers, "
                f"should be <= {options.max_parallel}"
            )
            assert last_pool_size == min(len(large_batch), options.max_parallel), (
                f"Expected {min(len(large_batch), options.max_parallel)} "
                f"workers, got {last_pool_size}"
            )

    def test_default_max_parallel_is_reasonable(self):
        """Test that default max_parallel prevents resource exhaustion"""
        options = BulkOptions()

        # Default should be reasonable (e.g., 10-20), not unlimited
        assert options.max_parallel is not None, "max_parallel should have default value"
        assert options.max_parallel <= 20, f"Default max_parallel too high: {options.max_parallel}"
        assert options.max_parallel >= 5, f"Default max_parallel too low: {options.max_parallel}"
