import unittest

from value_stream.resources import QATester, ResourcePool


class TestQATesterPool(unittest.TestCase):

    def test_validation(self):

        # happy paths
        _ = ResourcePool(class_name=QATester, limit=1)
        _ = ResourcePool(class_name=QATester, limit=None)

        # catch zero limit
        with self.assertRaises(ValueError):
            _ = ResourcePool(class_name=QATester, limit=0)

        # catch negative limit
        with self.assertRaises(ValueError):
            _ = ResourcePool(class_name=QATester, limit=-1)

    def test_limited_iteration(self):

        limit = 5

        qa_tester_pool = ResourcePool(class_name=QATester, limit=5)

        # run this twice to ensure successive iterations work
        for _ in range(2):
            i = 0
            for _ in qa_tester_pool:
                i += 1

            self.assertEqual(limit, i)

            with self.assertRaises(StopIteration):
                _ = next(qa_tester_pool)

    def test_unlimited_iteration(self):
        qa_tester_pool = ResourcePool(class_name=QATester, limit=None)

        for _ in range(42):
            _ = next(qa_tester_pool)
