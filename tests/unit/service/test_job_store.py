import time
import unittest

from value_stream.service.job_store import (
    CapacityExceeded, InMemoryJobStore, JobNotFound
)
from value_stream.service.schemas import ModelError
from value_stream.service.settings import ServiceSettings


class TestJobStore(unittest.TestCase):
    def test_indexed_errors_cursor_capacity_and_expiry(self):
        settings = ServiceSettings(
            max_active_jobs=1, max_queued_jobs=1,
            max_retained_jobs=2, job_ttl_seconds=0.02,
        )
        store = InMemoryJobStore(settings)
        first = store.create(2)
        second = store.create(1)
        with self.assertRaises(CapacityExceeded):
            store.create(1)
        self.assertTrue(store.start_model(first, 0))
        self.assertTrue(store.start_model(first, 1))
        store.finish_model(
            first, 0, result=None,
            error=ModelError(model_index=0, code="MODEL_FAILED", message="bad model"),
        )
        store.finish_model(
            first, 1, result=None,
            error=ModelError(model_index=1, code="MODEL_TIMEOUT", message="too slow"),
        )
        self.assertEqual(store.status(first).status, "completed_with_errors")
        self.assertEqual(store.page(first, 0).next_cursor, 2)
        self.assertEqual(len(store.page(first, 1).outcomes), 1)
        self.assertEqual(store.page(first, 2).outcomes, [])
        store.cancel(second)
        self.assertEqual(store.status(second).status, "cancelled")
        time.sleep(0.03)
        with self.assertRaises(JobNotFound):
            store.status(first)
        self.assertIsInstance(store.create(1), type(first))
