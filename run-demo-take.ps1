<#
.SYNOPSIS
    Runs one end-to-end take of the client outreach demo: starts a case,
    approves the drafted email, and lets it send.

.PARAMETER CaseId
    Case to run. Defaults to the shared demo case (Acme Corp Ltd).

.PARAMETER ClientId
    Client backing the case. Defaults to match demo-case-001.

.EXAMPLE
    .\run-demo-take.ps1
    .\run-demo-take.ps1 -CaseId "dryrun-priya" -ClientId "dryrun-client-priya"
#>

param(
    [string]$CaseId = "demo-case-001",
    [string]$ClientId = "demo-client-001"
)

$ErrorActionPreference = "Stop"

$Region          = "eu-central-1"
$StateMachineArn = "arn:aws:states:eu-central-1:477389928129:stateMachine:client-outreach-orchestration"
$QueueUrl        = "https://sqs.eu-central-1.amazonaws.com/477389928129/kyc-outreach-approval-queue"
$FunctionName    = "handle-approval-action"

$ExecName = "demo-take-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"

# Guard against collisions: if an earlier take was left paused (same case_id,
# same shared approval queue), a fresh run's approval step can't tell its own
# queue message apart from a stale one. Stop any other still-running
# executions and drain the queue before starting, so every take is isolated.
Write-Host "== Clearing any leftover executions / queue messages first ==" -ForegroundColor DarkGray
$others = aws stepfunctions list-executions --state-machine-arn $StateMachineArn --status-filter RUNNING --region $Region | ConvertFrom-Json
foreach ($ex in $others.executions) {
    aws stepfunctions stop-execution --execution-arn $ex.executionArn --region $Region | Out-Null
    Write-Host "  stopped leftover execution: $($ex.name)" -ForegroundColor DarkGray
}
do {
    $drain = aws sqs receive-message --queue-url $QueueUrl --region $Region --wait-time-seconds 1 --max-number-of-messages 10 | ConvertFrom-Json
    foreach ($m in $drain.Messages) {
        aws sqs delete-message --queue-url $QueueUrl --region $Region --receipt-handle $m.ReceiptHandle | Out-Null
    }
} while ($drain.Messages)

$inputPath = "$env:TEMP\start-input-$ExecName.json"
@{ case_id = $CaseId; client_id = $ClientId } | ConvertTo-Json -Compress | Out-File $inputPath -Encoding ascii

Write-Host "== Starting execution '$ExecName' for case '$CaseId' ==" -ForegroundColor Cyan
aws stepfunctions start-execution `
    --state-machine-arn $StateMachineArn `
    --name $ExecName `
    --input "file://$inputPath" `
    --region $Region | Out-Null

$ExecutionArn = "$($StateMachineArn -replace 'stateMachine', 'execution'):$ExecName"

Write-Host "Waiting for it to reach WaitForApproval..." -ForegroundColor Cyan
$reachedApproval = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    $history = aws stepfunctions get-execution-history --execution-arn $ExecutionArn --region $Region `
        --query "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name" --output text
    if ($history -match "WaitForApproval") {
        $reachedApproval = $true
        break
    }
}

if (-not $reachedApproval) {
    Write-Warning "Didn't see WaitForApproval after 30s. Check the console for execution '$ExecName' before continuing."
    exit 1
}

Write-Host "== Reached WaitForApproval. Approving... ==" -ForegroundColor Cyan

$approved = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    $raw = aws sqs receive-message --queue-url $QueueUrl --region $Region `
        --wait-time-seconds 5 --max-number-of-messages 1 | ConvertFrom-Json

    if (-not $raw.Messages) {
        Write-Warning "No message on the approval queue (attempt $attempt/3). Retrying..."
        continue
    }

    $msg  = $raw.Messages[0]
    $body = $msg.Body | ConvertFrom-Json

    if ($body.case_id -ne $CaseId) {
        # Belongs to a different run (yours or someone else's) -- leave it for
        # its owner and don't delete it. It'll become visible again shortly.
        Write-Warning "Queue message was for '$($body.case_id)', not '$CaseId' -- skipping, not deleting."
        continue
    }

    $approvalPayload = @{
        case_id    = $body.case_id
        decision   = "APPROVED"
        analyst_id = "$env:USERNAME@capgemini.com"
        task_token = $body.task_token
    } | ConvertTo-Json

    $payloadPath = "$env:TEMP\approval-$ExecName.json"
    $resultPath  = "$env:TEMP\approval-result-$ExecName.json"
    $approvalPayload | Out-File $payloadPath -Encoding ascii

    aws lambda invoke --function-name $FunctionName --region $Region `
        --cli-binary-format raw-in-base64-out `
        --payload "file://$payloadPath" $resultPath | Out-Null

    $result = Get-Content $resultPath | ConvertFrom-Json
    if ($result.results[0].resumed -eq $true) {
        aws sqs delete-message --queue-url $QueueUrl --region $Region `
            --receipt-handle $msg.ReceiptHandle | Out-Null
        $approved = $true
        break
    } else {
        Write-Warning "Approval invoke returned resumed=false (stale token). Retrying..."
    }
}

if (-not $approved) {
    Write-Warning "Could not approve after 3 attempts. Check the queue and execution manually."
    exit 1
}

Write-Host "== Approved. Email should arrive at arvind.c.kumar@capgemini.com shortly. ==" -ForegroundColor Green
Write-Host "Execution: $ExecutionArn"
Write-Host "Console:   https://$Region.console.aws.amazon.com/states/home?region=$Region#/v2/executions/details/$ExecutionArn"
