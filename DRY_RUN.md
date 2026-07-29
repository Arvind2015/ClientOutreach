# Dry Run — Client Outreach Orchestration

A self-contained test of the outbound pipeline: retrieve KYC data, draft an email, get it approved, send it, and simulate a client reply. Anyone on the team can run this independently.

| | |
|---|---|
| **Account** | 477389928129 (Admin_hack1) |
| **Region** | eu-central-1 |
| **State machine** | `client-outreach-orchestration` |
| **Shell** | Windows PowerShell 5.1 |

> **SES is in sandbox mode.** Only `arvind.c.kumar@capgemini.com` is a verified identity. Every test case — no matter who runs it — must use that address as `client_email`, or the send step will fail with "no recipient." The email will land in Arvind's inbox regardless of who ran the test; that's expected, not a bug.

> **Pick your own case ID** — don't reuse `demo-case-001`. It's already been through several test cycles and its state is contaminated (elevated follow-up count, mixed templates). Use your name as a suffix so nobody collides.
>
> **Only one person approves at a time.** Approvals are pulled from a shared queue. If you're testing at the same time as a colleague, coordinate in chat so you don't accidentally consume each other's approval message.

---

## 1. Set your variables

Everything below reuses these PowerShell variables. Swap `yourname` for something unique.

```powershell
$CaseId    = "dryrun-yourname"
$ClientId  = "dryrun-client-yourname"
$ExecName  = "dryrun-yourname-$(Get-Date -UFormat %s)"
$Region    = "eu-central-1"
$StateMachineArn = "arn:aws:states:eu-central-1:477389928129:stateMachine:client-outreach-orchestration"
$QueueUrl  = "https://sqs.eu-central-1.amazonaws.com/477389928129/kyc-outreach-approval-queue"
```

## 2. Seed the case record

Nothing in the pipeline creates `client_name` / `client_email` automatically — write them to the `Cases` table first, or the send step fails with "no recipient email."

```powershell
$item = @{
    case_id          = @{ S = $CaseId }
    client_id        = @{ S = $ClientId }
    client_name      = @{ S = "Dry Run Test Co ($env:USERNAME)" }
    client_email     = @{ S = "arvind.c.kumar@capgemini.com" }
    status           = @{ S = "NEW" }
    follow_up_count  = @{ N = "0" }
} | ConvertTo-Json -Depth 5

$item | Out-File "$env:TEMP\case-seed.json" -Encoding ascii
aws dynamodb put-item --table-name Cases --item "file://$env:TEMP/case-seed.json" --region $Region
```

**Expect:** no output on success. Confirm with:
```powershell
aws dynamodb get-item --table-name Cases --key ('{"case_id":{"S":"' + $CaseId + '"}}') --region eu-central-1
```

## 3. Start the execution

The KYC profile lookup is still a stub — every `client_id` gets back the same synthetic "Acme Corp Ltd" profile. That's expected; the real system-of-record adapter isn't wired up yet.

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $StateMachineArn `
  --name $ExecName `
  --input "{\"case_id\":\"$CaseId\",\"client_id\":\"$ClientId\"}" `
  --region $Region
```

**Expect:** status `RUNNING`, an `executionArn` returned.

## 4. Watch it reach approval

Open the console and confirm it's parked at `WaitForApproval` before continuing — this is the "analyst reviews the draft" step, standing in for a dashboard that doesn't exist yet.

AWS Console → Step Functions → State machines → **client-outreach-orchestration** → your execution name → watch the graph light up through `RetrieveKycProfile → RunGapAnalysis → DraftOutreach`, then pause.

**Expect:** graph paused, glowing at `WaitForApproval`.

## 5. Approve it

Pulls your case's message off the approval queue and invokes the approval handler directly — standing in for an analyst clicking "Approve."

```powershell
$msg  = aws sqs receive-message --queue-url $QueueUrl --region $Region `
          --wait-time-seconds 5 --max-number-of-messages 1 | ConvertFrom-Json
$body = $msg.Messages[0].Body | ConvertFrom-Json

# If $body.case_id doesn't match $CaseId, STOP — someone else's message.
# Wait ~30s for it to become visible again and try once more.
if ($body.case_id -ne $CaseId) {
    Write-Warning "Got a message for $($body.case_id), not $CaseId -- skipping."
} else {
    $approval = @{
        case_id    = $body.case_id
        decision   = "APPROVED"
        analyst_id = "$env:USERNAME@capgemini.com"
        task_token = $body.task_token
    } | ConvertTo-Json
    $approval | Out-File "$env:TEMP\approval.json" -Encoding ascii

    aws lambda invoke --function-name handle-approval-action --region $Region `
      --cli-binary-format raw-in-base64-out `
      --payload "file://$env:TEMP/approval.json" "$env:TEMP\approval-result.json"
    Get-Content "$env:TEMP\approval-result.json"

    aws sqs delete-message --queue-url $QueueUrl --region $Region `
      --receipt-handle $msg.Messages[0].ReceiptHandle
}
```

**Expect:** `"resumed": true` in the output.

## 6. Check the inbox

Within a few seconds, an email arrives at `arvind.c.kumar@capgemini.com` — subject contains a `CASEREF-…` token unique to your case. Back in the console, the graph should now show `SendOutreachEmail` and `StoreTaskTokenAndAwait` lit up, execution still "Running" — it's paused, waiting for a reply.

**Expect:** email received, execution paused on inbound wait.

## 7. Optional — simulate a client reply

Real inbound email isn't wired up yet (needs domain/MX setup). This fakes a client sending back the two requested documents, so you can watch validation and the follow-up decision run for real.

```powershell
$reply = @{
    attachments = @(
        @{
            attachment_id = "sim-cert-001"
            classification = "CERTIFICATE_OF_INCORPORATION"
            extracted_fields = @{
                company_name = "Dry Run Test Co ($env:USERNAME)"
                registration_number = "12345678"
                incorporation_date = "2015-03-14"
            }
            classification_confidence = 0.97
            extraction_confidence = 0.95
        },
        @{
            attachment_id = "sim-poa-001"
            classification = "PROOF_OF_ADDRESS"
            extracted_fields = @{
                full_name = "Dry Run Test Co ($env:USERNAME)"
                address = "1 Fleet Street, London, EC4Y 1AA, UK"
                document_date = "2026-06-01"
            }
            classification_confidence = 0.94
            extraction_confidence = 0.92
        }
    )
} | ConvertTo-Json -Depth 6
$reply | Out-File "$env:TEMP\reply.json" -Encoding ascii

$token = aws dynamodb get-item --table-name Cases --region $Region `
  --key ('{"case_id":{"S":"' + $CaseId + '"}}') `
  --query "Item.sfn_task_token.S" --output text

aws stepfunctions send-task-success --task-token $token `
  --task-output "file://$env:TEMP/reply.json" --region $Region
```

**Expect:** execution resumes, runs `ValidateAndUpdate → ProcessFollowUp`, then loops back to a fresh `DraftOutreach` (a follow-up reminder — this is correct: the KYC-write path is still a stub, so the case never shows fully compliant yet). Repeat step 5 if you want to watch it loop again.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Approval returns `"resumed": false` | Task token is stale — belongs to an execution that already moved on or ended | Re-run step 5; it'll pull the next message. If the queue's empty, your execution may not have reached `WaitForApproval` yet |
| No email arrives | `client_email` wasn't seeded, or isn't the verified sandbox address | Re-check step 2 — it must be exactly `arvind.c.kumar@capgemini.com` |
| Execution status `FAILED` | Real error somewhere in the chain | Check the execution's event history in the console for the failed state, then CloudWatch logs for that Lambda |
| Draft uses "follow-up-reminder" not "standard-outreach" on a fresh case | Your case_id was reused from an earlier test | Pick a new, never-used `$CaseId` |

---

_Client Outreach Agent · Stream 5 orchestration · updated 2026-07-29_
