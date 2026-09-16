"""One model per child process; reads and writes bounded JSON over stdio."""

import hashlib
import json
import random
import sys
from typing import Any

from pydantic import BaseModel, Field

from value_stream.simulation import DefaultSimulationPolicy, Simulation

from .codec import decode_model, decode_tasks, encode_result
from .schemas import JobRequest, ModelError


class WorkerPayload(BaseModel):
    model_index: int = Field(ge=0)
    request: JobRequest
    max_outcome_bytes: int = Field(default=8 * 1024 * 1024, gt=0)


class WorkerIndex(BaseModel):
    model_index: int = Field(default=0, ge=0)


def derive_seed(job_seed: int, model_index: int) -> int:
    digest = hashlib.sha256(f"{job_seed}:{model_index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def run(payload: object) -> dict[str, dict[str, Any]]:
    validated = WorkerPayload.model_validate(payload)
    index = validated.model_index
    request = validated.request
    if len(request.models) != 1:
        raise ValueError("worker payload must contain one model")
    if request.seed is not None:
        random.seed(derive_seed(request.seed, index))
    model = decode_model(request.models[0])
    tasks = decode_tasks(request.tasks)
    result = Simulation().execute(
        model=model, tasks=tasks, policy=DefaultSimulationPolicy()
    )
    encoded = encode_result(result, index)
    max_bytes = validated.max_outcome_bytes
    if len(encoded.model_dump_json().encode("utf-8")) > max_bytes:
        return {
            "error": ModelError(
                model_index=index,
                code="RESULT_TOO_LARGE",
                message="model result exceeds configured size limit",
            ).model_dump(mode="json")
        }
    return {"result": encoded.model_dump(mode="json")}


def main() -> None:
    payload: object = None
    try:
        payload = json.load(sys.stdin)
        output = run(payload)
    except Exception as exc:  # model failures must be reported without stopping the batch
        try:
            index = WorkerIndex.model_validate(payload).model_index
        except Exception:
            index = 0
        output = {
            "error": ModelError(
                model_index=index, code="MODEL_FAILED", message=str(exc)
            ).model_dump(mode="json")
        }
    json.dump(output, sys.stdout, allow_nan=False)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
