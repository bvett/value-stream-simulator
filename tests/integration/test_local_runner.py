import unittest
from unittest.mock import patch

from value_stream.client import SimulationRunner
from value_stream.client.web.errors import BatchSimulationError
from value_stream.client.views import MetadataViewer, ResultViewer
from value_stream.resources import Developer, QATester, Toolchain
from value_stream.simulation import Model, SimulationResult
from value_stream.task import Task
from value_stream.service.app import create_app
from value_stream.service.settings import ServiceSettings


class TestLocalRunner(unittest.TestCase):
    def test_local_service_and_viewers(self):
        tasks = [Task(initial_value=1, story_points=1, task_name="A")]
        models = [
            Model(
                developer_team=[Developer(name="Dev")],
                deployment_cadence=cadence,
                qa_testers=QATester.create_pool(limit=1),
                toolchain_pool=Toolchain.create_pool(
                    limit=1, deployment_duration=0.25
                ),
            )
            for cadence in (0, 1)
        ]
        with SimulationRunner() as runner:
            results = runner.execute(tasks=tasks, models=models, seed=11)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(isinstance(r, SimulationResult) for r in results))
            self.assertIs(results[0].summary_result.model, models[0])
            self.assertIs(results[1].metadata.model, models[1])
            self.assertEqual(len(ResultViewer(results).data), 2)
            metadata = MetadataViewer(results, task_states=runner.task_states())
            self.assertEqual(len(metadata._results_dict), 2)

    def test_reuses_local_service(self):
        first = SimulationRunner()
        second = SimulationRunner()
        self.assertEqual(first.client.service_url, second.client.service_url)
        first.close()
        second.close()

    def test_partial_failure_is_indexed_in_runner_error(self):
        tasks = [Task(initial_value=1, story_points=1)]
        models = [
            Model(
                developer_team=[Developer()],
                deployment_cadence=0,
                qa_testers=QATester.create_pool(limit=1),
                toolchain_pool=Toolchain.create_pool(
                    limit=1, deployment_duration=0.25, failure_rate=rate
                ),
            )
            for rate in (1, 0)
        ]
        with patch(
            "value_stream.client.web.local_service.create_app",
            side_effect=lambda: create_app(ServiceSettings(max_model_seconds=1)),
        ):
            with SimulationRunner() as runner:
                with self.assertRaises(BatchSimulationError) as caught:
                    runner.execute(tasks=tasks, models=models, seed=4)
        self.assertEqual(set(caught.exception.errors), {0})
        self.assertEqual([i for i, _ in caught.exception.successful_results], [1])
