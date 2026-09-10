import unittest

from pandas import DataFrame

from value_stream.core import WorkflowStateName
from value_stream.resources import DeveloperFactory, QATester, Toolchain
from value_stream.task import EventStatus, TaskFactory, TaskEvent
from value_stream.simulation import DefaultSimulationPolicy, Model, Simulation


class TestSimulation(unittest.TestCase):

    def test_simple_model_without_support_or_failures(self):
        num_developers = 2
        developer_efficiency = 1.0
        qa_tester_time_cost = 0.1
        num_tasks = 10

        task_initial_value = 1
        task_story_points = 2

        deployment_cadence = 0

        qa_tester_pool = QATester.create_pool(
            limit=None, time_cost=qa_tester_time_cost)
        toolchain_pool = Toolchain.create_pool(
            limit=None, deployment_duration=.25)

        simulation = Simulation()

        developers = DeveloperFactory().create(
            count=num_developers, efficiency=developer_efficiency)

        tasks = TaskFactory(initial_value=task_initial_value,
                            story_points=task_story_points,
                            depreciation_rate=0.05).create(num_tasks)

        model = Model(developer_team=developers,
                      deployment_cadence=deployment_cadence,
                      qa_testers=qa_tester_pool,
                      toolchain_pool=toolchain_pool,
                      support_interval=None)

        result = simulation.execute(model=model,
                                    tasks=tasks,
                                    policy=DefaultSimulationPolicy())

        summary = result.summary_result

        resource_metadata = DataFrame(
            [vars(x) for x in result.metadata.resource_metadata])
        event_metadata = DataFrame([vars(x)
                                   for x in result.metadata.event_metadata])

        max_delivery_t = event_metadata[(event_metadata["event"] == WorkflowStateName.DELIVERY) & (
            event_metadata["status"] == EventStatus.SUCCESS)]["time"].max()

        self.assertEqual(summary.completion_time, max_delivery_t)

        # validate total loss

        mean_loss = event_metadata[(event_metadata["event_type"] == TaskEvent.EventType.END)][["event", "loss"]].groupby(
            "event").mean(numeric_only=True)

        total_mean_loss: float = mean_loss.sum(
            numeric_only=True).array[0]

        self.assertAlmostEqual(summary.loss, total_mean_loss)

        total_original_value = num_tasks * task_initial_value

        # validate delivered value by applying loss to total original value

        self.assertAlmostEqual(summary.total_delivered_value,
                               total_original_value * (1+summary.loss))

        # Validate the amount of time a resource is busy against the amount of time events were in the respective workflow state

        resource_summary = resource_metadata.groupby(
            'state').sum(numeric_only=True)[['success_t', 'waiting_t']]

        event_summary = event_metadata.groupby('event').sum(
            numeric_only=True)['duration']

        for index, row in resource_summary.iterrows():
            resource_total = row['success_t']
            event_total = event_summary.at[index]

            self.assertEqual(resource_total, event_total)

        pending_development_total = event_summary.at['pending']
        resource_waiting_total = resource_summary.at['development', 'waiting_t']
        self.assertEqual(pending_development_total, resource_waiting_total)
