"""
Stream 5 — Store Task Token (Task 7.1 / AwaitClientResponse state)

Invoked via arn:aws:states:::lambda:invoke.waitForTaskToken so the state
machine pauses here waiting for the Inbound Analysis Agent (Stream 4) to
resume it by calling sfn:SendTaskSuccess / sfn:SendTaskFailure with this token.

This Lambda's only job:
  1. Write the Step Functions task token into the Cases table so the Inbound
     Analysis Agent can retrieve it when a matching inbound email arrives.
  2. Update the case status to AWAITING_RESPONSE.
  3. Return immediately — the state machine stays paused until the token is
     used externally (by Stream 4) or the HeartbeatTimeout fires.

Inputs (injected by Step Functions via Parameters):
  - case_id: str
  - task_token: str   ← injected as $$.Task.Token by the state machine

The state machine must NOT await a response from this Lambda function itself —
it awaits the external SendTaskSuccess call. This is why the resource is
lambda:invoke.waitForTaskToken, not just lambda:invoke.
"""

import os
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
cases_table = dynamodb.Table(os.environ["CASES_TABLE"])


def handler(event, context):
    case_id = event["case_id"]
    task_token = event["task_token"]

    # Write token and flip status — Stream 4 reads this token when
    # a correlated inbound email arrives and calls sfn:SendTaskSuccess
    cases_table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=(
            "SET #s = :s, sfn_task_token = :t, updated_at = :ts"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "AWAITING_RESPONSE",
            ":t": task_token,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Do NOT return a value — the state machine resumes only when
    # Stream 4 calls sfn:SendTaskSuccess(taskToken, result)
