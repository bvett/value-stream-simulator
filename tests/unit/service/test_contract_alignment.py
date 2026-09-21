import inspect
import io
import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from value_stream.resources import Developer, QATester, ResourceMetadata, Toolchain
from value_stream.service.codec import (
    decode_model, decode_result, decode_tasks, encode_model, encode_request, encode_result
)
from value_stream.service.schemas import (
    DeveloperInput, MetadataData, ModelInput, QAInput, ResourceMetadataData,
    ResultData, SummaryData, TaskEventData, TaskInput, ToolchainInput,
)
from value_stream.service.worker import derive_seed, main, run
from value_stream.service.app import create_app
from value_stream.simulation import (
    DefaultSimulationPolicy, Model, Simulation, SimulationMetadata, SummaryResult
)
from value_stream.task import Task, TaskEvent


def constructor_names(cls):
    return {
        name for name in inspect.signature(cls.__init__).parameters
        if name != "self"
    }


class TestContractAlignment(unittest.TestCase):
    def test_input_constructor_fields(self):
        self.assertEqual(set(Model.model_fields), set(ModelInput.model_fields))
        self.assertEqual(constructor_names(Task), set(TaskInput.model_fields))
        self.assertEqual(set(Developer.model_fields), set(DeveloperInput.model_fields))
        self.assertEqual(set(QATester.model_fields), set(QAInput.model_fields))
        self.assertEqual(set(Toolchain.model_fields), set(ToolchainInput.model_fields))

    def test_output_fields(self):
        self.assertEqual(set(SummaryResult.model_fields) - {"model"}, set(SummaryData.model_fields))
        self.assertEqual(
            set(SimulationMetadata.model_fields) - {"model"},
            set(MetadataData.model_fields),
        )
        self.assertEqual(set(TaskEvent.model_fields), set(TaskEventData.model_fields))
        self.assertEqual(set(ResourceMetadata.model_fields), set(ResourceMetadataData.model_fields))

    def test_model_and_result_round_trip(self):
        model = Model(
            developer_team=[Developer(efficiency=1.3, name="Distinct")],
            deployment_cadence=2,
            qa_testers=QATester.create_pool(
                limit=2, time_cost=0.2, failure_rate=0.1, failure_cost=0.3
            ),
            toolchain_pool=Toolchain.create_pool(
                limit=3, deployment_duration=0.4, failure_rate=0.1
            ),
            support_interval=7,
            support_task_story_points=1.5,
        )
        task = Task(
            initial_value=3, story_points=2, depreciation_rate=0.01,
            task_name="Distinct", creation_sim_t=1,
        )
        encoded = encode_request([task], [model], seed=55)
        self.assertEqual(set(vars(model)) - {"team_size"}, set(ModelInput.model_fields))
        decoded_model = decode_model(encoded.models[0])
        self.assertEqual(encode_model(decoded_model), encoded.models[0])
        self.assertEqual(decode_tasks(encoded.tasks)[0].value(), task.value())

        payload = {
            "model_index": 0,
            "request": encoded.model_dump(mode="json"),
        }
        worker_output = run(payload)["result"]
        data = ResultData.model_validate(worker_output)
        reconstructed = decode_result(data, model)
        result = decode_result(encode_result(reconstructed, 0), model)
        self.assertIs(result.summary_result.model, model)
        self.assertTrue(result.metadata.event_metadata)
        self.assertTrue(result.metadata.resource_metadata)

        random_state = random.getstate()
        try:
            random.seed(derive_seed(55, 0))
            direct = Simulation().execute(
                model=decode_model(encoded.models[0]),
                tasks=decode_tasks(encoded.tasks),
                policy=DefaultSimulationPolicy(),
            )
        finally:
            random.setstate(random_state)
        direct_data = encode_result(direct, 0).model_dump(mode="json")
        self.assertEqual(worker_output["summary_result"], direct_data["summary_result"])
        self.assertEqual(
            worker_output["metadata"]["resource_metadata"],
            direct_data["metadata"]["resource_metadata"],
        )
        for left, right in zip(
            worker_output["metadata"]["event_metadata"],
            direct_data["metadata"]["event_metadata"],
        ):
            self.assertEqual(
                {k: v for k, v in left.items() if k != "resource_id"},
                {k: v for k, v in right.items() if k != "resource_id"},
            )

    def test_concrete_resource_lists_and_unlimited_pool(self):
        concrete = Model(
            developer_team=[Developer()], deployment_cadence=0,
            qa_testers=[QATester(time_cost=0.2)],
            toolchain_pool=[Toolchain(deployment_duration=0.4)],
        )
        encoded = encode_model(concrete)
        self.assertEqual(encoded.qa_testers.kind, "list")
        self.assertEqual(encoded.toolchain_pool.kind, "list")
        self.assertEqual(encode_model(decode_model(encoded)), encoded)
        unlimited = Model(
            developer_team=[Developer()], deployment_cadence=0,
            qa_testers=QATester.create_pool(limit=None),
            toolchain_pool=Toolchain.create_pool(limit=1, deployment_duration=0.4),
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            encode_model(unlimited)

    def test_worker_reports_indexed_validation_error(self):
        output = io.StringIO()
        payload = {"model_index": 7, "request": {"tasks": [], "models": []}}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", output):
            main()
        self.assertEqual(json.loads(output.getvalue())["error"]["model_index"], 7)

    def test_seed_is_stable(self):
        self.assertEqual(derive_seed(123, 0), derive_seed(123, 0))
        self.assertNotEqual(derive_seed(123, 0), derive_seed(123, 1))

    def test_reviewed_openapi_matches_application(self):
        path = Path(__file__).parents[3] / "src/value_stream/service/openapi.json"
        self.assertEqual(json.loads(path.read_text()), create_app().openapi())
