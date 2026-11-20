"""The only module that reads the environment and builds real clients (SB-CFG-3).

``deps()`` is created on first use, so importing a handler module in a test needs no AWS.
Environment variables hold names only: never a secret or a token.
"""

from __future__ import annotations

import functools
import os
import time
from typing import Any

import httpx

from core.scan.errors import GITHUB_AUTH_FAILED
from scan.store import DynamoScanTable, S3Artefacts
from workflow.common import GITHUB_BASE_URL, Deps

SERVICE = "graveyard"


@functools.cache
def env_name() -> str:
    return os.environ["GRAVEYARD_ENV"]


@functools.cache
def logger() -> Any:
    from aws_lambda_powertools import Logger

    return Logger(service=SERVICE)


@functools.cache
def tracer() -> Any:
    from aws_lambda_powertools import Tracer

    return Tracer(service=SERVICE)


def emit_metric(name: str, value: float, unit: str = "Count", **dimensions: str) -> None:
    from aws_lambda_powertools.metrics import MetricUnit, single_metric

    with single_metric(
        name=name,
        unit=MetricUnit(unit),
        value=value,
        namespace=f"Graveyard/{env_name()}",
    ) as metric:
        for key, dim in dimensions.items():
            metric.add_dimension(name=key, value=dim)


@functools.cache
def deps() -> Deps:
    import boto3
    from aws_lambda_powertools.utilities import parameters

    logger()
    prefix = f"/graveyard/{env_name()}/"
    secrets = boto3.client("secretsmanager")
    secret_id = os.environ.get("READER_SECRET_ID", "")

    def param(name: str) -> str:
        return str(parameters.get_parameter(prefix + name, max_age=60))

    def secret() -> str:
        try:
            return str(secrets.get_secret_value(SecretId=secret_id)["SecretString"])
        except Exception:  # an empty container (key not set yet) or no access
            raise GITHUB_AUTH_FAILED from None

    def github() -> httpx.Client:
        contact = param("sources/contact")
        return httpx.Client(
            base_url=GITHUB_BASE_URL,
            timeout=httpx.Timeout(10.0),
            headers={"X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"graveyard ({contact})"},
        )

    return Deps(
        table=DynamoScanTable(boto3.resource("dynamodb"), os.environ["TABLE_NAME"]),
        artefacts=S3Artefacts(boto3.client("s3"), os.environ["BUCKET_NAME"]),
        param=param,
        secret=secret,
        github=github,
        now=time.time,
        metric=emit_metric,
    )


def begin(event: dict[str, Any]) -> Deps:
    """Set the correlation ID (``scanId``, SB-OBS-2) and return the dependencies."""
    scan_id = event.get("scanId")
    if isinstance(scan_id, str):
        logger().set_correlation_id(scan_id[:64])
    return deps()
