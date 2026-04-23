import unittest

from value_stream.resources import ToolchainPool


class TestToolchainPool(unittest.TestCase):

    def test_validation(self):
        # happy paths: positive limit and unlimited
        _ = ToolchainPool(limit=1)
        _ = ToolchainPool(limit=None)

        # catch zero limit
        with self.assertRaises(ValueError):
            _ = ToolchainPool(limit=0)

        # catch negative limit
        with self.assertRaises(ValueError):
            _ = ToolchainPool(limit=-1)

    def test_limited_iteration(self):

        limit = 3
        toolchain_pool = ToolchainPool(
            limit=limit, deployment_duration=1)

        # test for successive iterations
        for _ in range(2):
            i = 0
            for _ in toolchain_pool:
                i += 1

            self.assertEqual(limit, i)

            with self.assertRaises(StopIteration):
                _ = next(toolchain_pool)

    def test_unlimited_iteration(self):

        toolchain_pool = ToolchainPool(limit=None, deployment_duration=1)

        # Realistically, not practical or useful to test up to sys.maxsize
        # Test to ensure basic mechanism works, then deal with an n+1 bug
        # if it ever surfaces

        for _ in range(10):
            _ = next(toolchain_pool)
