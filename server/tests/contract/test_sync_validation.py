"""Unit tests for the bounded sync-envelope validation.

Guards the client/server TraceStatus vocabulary alignment: the client's canonical
initial status is "proposed", which the server must accept (a mismatch here
rejects every freshly generated trace link with 422 "Invalid TraceLink status"
and blocks the whole child-op batch).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tracelab_server.schemas.cloud import SyncOperation
from tracelab_server.services.sync_validation import validate_domain_operation

WORKSPACE = "684e1148-90a8-4eec-92c0-e7611c8a20be"
DEVICE = "684e1148-90a8-4eec-92c0-e7611c8a20be"
OP = "684e1148-90a8-4eec-92c0-e7611c8a20be"
PROJECT = "4763d8d7-fbf3-4520-a187-ad899da0d2f0"
ENTITY = "4763d8d7-fbf3-4520-a187-ad899da0d2f0"


def _trace_op(status: str) -> SyncOperation:
    return SyncOperation(
        workspace_id=WORKSPACE,
        device_id=DEVICE,
        client_operation_id=OP,
        entity_type="trace_link",
        entity_public_id=ENTITY,
        operation="upsert",
        base_version=0,
        payload={
            "project_public_id": PROJECT,
            "paper_ref": "p1",
            "code_ref": "c1",
            "status": status,
        },
    )


@pytest.mark.parametrize("status", ["proposed", "accepted", "rejected", "stale"])
def test_valid_trace_statuses_accepted(status: str) -> None:
    validate_domain_operation(_trace_op(status))  # must not raise


def test_invalid_trace_status_rejected() -> None:
    with pytest.raises(HTTPException) as excinfo:
        validate_domain_operation(_trace_op("bogus"))
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "Invalid TraceLink status"
