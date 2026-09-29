import logging
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from value_stream.client.web.local_service import _LocalService


class TestLocalService(unittest.TestCase):
    def test_preserves_host_logging_configuration(self):
        with ExitStack() as stack:
            loggers = [
                logging.getLogger(name)
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
            ]
            handlers = [logging.NullHandler()]
            for logger in loggers:
                stack.enter_context(patch.object(logger, "level", logging.INFO))
                stack.enter_context(patch.object(logger, "handlers", handlers))
                stack.enter_context(patch.object(logger, "propagate", False))
                stack.enter_context(patch.object(logger, "disabled", False))

            service = _LocalService()
            try:
                for logger in loggers:
                    with self.subTest(logger=logger.name):
                        self.assertEqual(logger.level, logging.INFO)
                        self.assertFalse(logger.disabled)
                        self.assertIs(logger.handlers, handlers)
                        self.assertFalse(logger.propagate)
            finally:
                service.stop()
