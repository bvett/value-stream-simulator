import unittest

from simpy import Environment
from simpy.events import AllOf


from value_stream.factory import TaskFactory
from value_stream.resources import Developer, QATester, Toolchain
from value_stream.simulation import DefaultSimulationPolicy
from value_stream.workflow import SDLCWorkflow, TaskStore, ResourceOperator


class TestSDLCWorkflow(unittest.TestCase):
    def test_all(self):

        env = Environment()

        signal = env.event()

        num_tasks = 10
        factory = TaskFactory(story_points=1, initial_value=1)

        tasks = factory.create(count=num_tasks)

        pending_items = TaskStore(
            env=env, name=SDLCWorkflow.WorkflowState.PENDING)

        policy = DefaultSimulationPolicy()

        developer_manager = ResourceOperator(env, resources=[Developer()],
                                             workflow_policy=policy,
                                             resource_policy=policy)

        qa_tester_pool = QATester.create_pool(
            limit=1, failure_rate=0)

        toolchain_pool = Toolchain.create_pool(
            limit=1,
            deployment_duration=1,
            failure_rate=0)

        qa_manager = ResourceOperator(
            env, qa_tester_pool, workflow_policy=policy, resource_policy=policy)

        toolchain_manager = ResourceOperator(
            env, toolchain_pool, workflow_policy=policy, resource_policy=policy, cadence=0)

        workflow = SDLCWorkflow()

        env.process(workflow.start(env=env, tasks=tasks,
                                   pending=pending_items, signal=signal,
                                   developer_manager=developer_manager,
                                   qa_manager=qa_manager,
                                   toolchain_manager=toolchain_manager))

        completed = env.run(AllOf(env, [signal]))

        self.assertEqual(0, len(pending_items.items))

        completed_tasks = []
        for t in completed.values():  # type: ignore
            completed_tasks.extend(t)

        self.assertIsNotNone(completed_tasks)
        self.assertEqual(num_tasks, len(completed_tasks))
