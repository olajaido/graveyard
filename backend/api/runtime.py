"""Builds the real API dependencies. With ``workflow/runtime.py``, the only code that reads
the environment (names only; SB-CFG-3)."""

from __future__ import annotations

import functools
import json
import os
import secrets
import time
from collections.abc import Mapping
from typing import Any

from api.routes import ApiDeps
from scan.store import DynamoScanTable


class SfnRunner:
    def __init__(self, client: Any, state_machine_arn: str) -> None:
        self._client = client
        self._arn = state_machine_arn

    def start(self, scan_id: str, payload: Mapping[str, Any]) -> None:
        self._client.start_execution(
            stateMachineArn=self._arn, name=scan_id, input=json.dumps(payload)
        )


@functools.cache
def deps() -> ApiDeps:
    import boto3
    from aws_lambda_powertools import Logger
    from aws_lambda_powertools.utilities import parameters

    Logger(service="graveyard")
    prefix = f"/graveyard/{os.environ['GRAVEYARD_ENV']}/"

    def param(name: str) -> str:
        return str(parameters.get_parameter(prefix + name, max_age=60))

    return ApiDeps(
        table=DynamoScanTable(boto3.resource("dynamodb"), os.environ["TABLE_NAME"]),
        runner=SfnRunner(boto3.client("stepfunctions"), os.environ["STATE_MACHINE_ARN"]),
        param=param,
        now=time.time,
        random=secrets.token_bytes,
    )
