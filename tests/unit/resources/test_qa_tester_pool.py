import unittest

from value_stream.resources import QATester


class TestQATesterPool(unittest.TestCase):

    def test_validation(self):

        # happy paths
        _ = QATester.create_pool(limit=1)
        _ = QATester.create_pool(limit=None)

        # catch zero limit
        with self.assertRaises(ValueError):
            _ = QATester.create_pool(limit=0)

        # catch negative limit
        with self.assertRaises(ValueError):
            _ = QATester.create_pool(limit=-1)

    def test_limited_iteration(self):

        limit = 5

        qa_tester_pool = QATester.create_pool(limit=5)

        # run this twice to ensure successive iterations work
        for _ in range(2):
            i = 0
            for _ in qa_tester_pool:
                i += 1

            self.assertEqual(limit, i)

            with self.assertRaises(StopIteration):
                _ = next(qa_tester_pool)

    def test_unlimited_iteration(self):
        qa_tester_pool = QATester.create_pool(limit=None)

        for _ in range(42):
            _ = next(qa_tester_pool)
