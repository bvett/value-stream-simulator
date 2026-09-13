import copy
from enum import Enum
from typing import Optional
import unittest
from simpy import Environment
from value_stream.resources import ResourceTracker, ResourceMetadata
from value_stream.task import TaskState, EventStatus


class TestResourceTracker(unittest.TestCase):

    class State(TaskState):
        FIRST = "first"
        SECOND = "second"
        THIRD = "third"

    def setUp(self):
        self.start_sim_t = 100
        self.env = Environment(initial_time=self.start_sim_t)
        self.tracker = ResourceTracker(self.env)

    @classmethod
    def summarize(cls, tracker: ResourceTracker):
        result: dict[TaskState, ResourceMetadata] = {}

        def add(x: Optional[float], y: Optional[float]) -> Optional[float]:
            if x is None:
                x = y
            elif y is not None:
                x += y

            return x

        for metadata in tracker.data:
            if metadata.state not in result:
                result[metadata.state] = copy.copy(metadata)
            else:
                summary_data = result[metadata.state]
                summary_data.active += metadata.active
                summary_data.allocated += metadata.allocated
                summary_data.waiting += metadata.waiting

                summary_data.failure_t = add(
                    summary_data.failure_t, metadata.failure_t)

                summary_data.idle_t = add(summary_data.idle_t, metadata.idle_t)

                summary_data.interruption_t = add(
                    summary_data.interruption_t, metadata.interruption_t)

                summary_data.success_t = add(
                    summary_data.success_t, metadata.success_t)

                summary_data.waiting_t = add(
                    summary_data.waiting_t, metadata.waiting_t)

        return result

    def test_register(self):

        self.tracker.register(self.State.THIRD)
        self.tracker.register(self.State.THIRD)
        self.tracker.register(self.State.SECOND)
        # assert totals by state.  Need util func.

        summary_data = self.summarize(self.tracker)

        self.assertEqual(2, summary_data[self.State.THIRD].allocated)
        self.assertEqual(1, summary_data[self.State.SECOND].allocated)

    def test_start_and_complete_work(self):

        for _ in range(3):
            self.tracker.register(self.State.FIRST)

        self.tracker.start_work(self.State.FIRST, 10)
        self.tracker.start_work(self.State.FIRST, 20)
        self.tracker.start_work(self.State.FIRST, 30)

        summary_data = self.summarize(self.tracker)

        self.assertEqual(60, summary_data[self.State.FIRST].idle_t)
        self.assertEqual(3, summary_data[self.State.FIRST].active)

        self.tracker.complete_work(self.State.FIRST, EventStatus.SUCCESS, 7)
        summary_data = self.summarize(self.tracker)

        self.assertEqual(2, summary_data[self.State.FIRST].active)
        self.assertEqual(3, summary_data[self.State.FIRST].allocated)
        self.assertEqual(7, summary_data[self.State.FIRST].success_t)

        self.tracker.complete_work(self.State.FIRST, EventStatus.FAILURE, 12)
        self.tracker.complete_work(self.State.FIRST, EventStatus.SUCCESS, 3)
        summary_data = self.summarize(self.tracker)

        self.assertEqual(10, summary_data[self.State.FIRST].success_t)
        self.assertEqual(12, summary_data[self.State.FIRST].failure_t)
        self.assertEqual(0, summary_data[self.State.FIRST].active)
        self.assertEqual(3, summary_data[self.State.FIRST].allocated)

    def test_interruption(self):
        for _ in range(3):
            self.tracker.register(self.State.FIRST)

        self.tracker.start_work(self.State.FIRST, 0)
        self.tracker.interruption(self.State.FIRST, 55)
        self.tracker.complete_work(self.State.FIRST, EventStatus.SUCCESS, 10)

        summary_data = self.summarize(self.tracker)[self.State.FIRST]

        self.assertEqual(55, summary_data.interruption_t)
        self.assertEqual(0, summary_data.active)
        self.assertEqual(10, summary_data.success_t)
        self.assertIsNone(summary_data.failure_t)

    def test_start_and_complete_waiting(self):
        state = self.State.SECOND
        for _ in range(3):
            self.tracker.register(state)

        self.tracker.start_waiting(state)
        summary_data = self.summarize(self.tracker)[state]
        self.assertEqual(0, summary_data.active)
        self.assertEqual(3, summary_data.allocated)
        self.assertEqual(1, summary_data.waiting)

        self.tracker.complete_waiting(state, 32)
        self.tracker.start_waiting(state)
        self.tracker.complete_waiting(state, 64)

        summary_data = self.summarize(self.tracker)[state]

        self.assertEqual(0, summary_data.active)
        self.assertEqual(3, summary_data.allocated)
        self.assertEqual(96, summary_data.waiting_t)
        self.assertEqual(0, summary_data.waiting)
