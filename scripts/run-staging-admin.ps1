param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('migrate', 'provision-runtime-role', 'bootstrap-owner', 'retain')]
    [string]$Command,
    [string]$Email,
    [string]$AccountName,
    [ValidateRange(1,36600)][int]$Days = 30,
    [ValidateRange(1,10000)][int]$BatchSize = 1000,
    [string]$Profile = 'traceworth-staging',
    [string]$Region = 'us-east-2'
)
# This script CHANGES the selected staging database. Run only after reviewing
# the deployment plan and filling the referenced Secrets Manager values.
$ErrorActionPreference = 'Stop'
$terraformDirectory = Join-Path $PSScriptRoot '../infra/staging'
$outputJson = & terraform "-chdir=$terraformDirectory" output -json
if ($LASTEXITCODE -ne 0) { throw 'Unable to read staging Terraform outputs.' }
$outputs = $outputJson | ConvertFrom-Json
$definition = $outputs.admin_task_definition.value
if (-not $definition) { throw 'Deploy the reviewed digest-pinned admin task definition first.' }
$arguments = @($Command)
if ($Command -eq 'bootstrap-owner') {
    if (-not $Email -or -not $AccountName) { throw 'Bootstrap requires -Email and -AccountName.' }
    $arguments += @('--email', $Email, '--account-name', $AccountName, '--password-env')
}
if ($Command -eq 'retain') {
    $arguments += @('--days', "$Days", '--batch-size', "$BatchSize")
}
$request = @{
    cluster = $outputs.cluster_name.value
    taskDefinition = $definition
    launchType = 'FARGATE'
    platformVersion = '1.4.0'
    count = 1
    networkConfiguration = @{
        awsvpcConfiguration = @{
            subnets = @($outputs.private_subnets.value)
            securityGroups = @($outputs.task_security_group.value)
            assignPublicIp = 'DISABLED'
        }
    }
    overrides = @{ containerOverrides = @(@{ name = 'admin'; command = $arguments }) }
}
$requestPath = [System.IO.Path]::GetTempFileName()
try {
    # Secret values never enter this file or the AWS CLI arguments.
    [System.IO.File]::WriteAllText($requestPath, ($request | ConvertTo-Json -Depth 10))
    $runJson = & aws ecs run-task --profile $Profile --region $Region --cli-input-json "file://$requestPath" --output json
    if ($LASTEXITCODE -ne 0) { throw 'ECS run-task failed.' }
    $run = $runJson | ConvertFrom-Json
    if ($run.failures.Count -gt 0 -or $run.tasks.Count -ne 1) { throw 'ECS did not launch exactly one admin task. Inspect ECS task failures.' }
    $taskArn = $run.tasks[0].taskArn
    Write-Output "Waiting for admin task: $taskArn"
    & aws ecs wait tasks-stopped --profile $Profile --region $Region --cluster $outputs.cluster_name.value --tasks $taskArn
    if ($LASTEXITCODE -ne 0) { throw "Wait failed; inspect task $taskArn before running another admin task." }
    $resultJson = & aws ecs describe-tasks --profile $Profile --region $Region --cluster $outputs.cluster_name.value --tasks $taskArn --output json
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect admin task result.' }
    $result = $resultJson | ConvertFrom-Json
    $container = @($result.tasks[0].containers | Where-Object name -eq 'admin')
    if ($container.Count -ne 1 -or $null -eq $container[0].exitCode -or $container[0].exitCode -ne 0) {
        throw "Admin task did not succeed. Inspect ECS/CloudWatch for task $taskArn; do not enable the API yet."
    }
    Write-Output "Admin command '$Command' succeeded. Inspect its CloudWatch output before the next step."
} finally {
    Remove-Item -LiteralPath $requestPath -ErrorAction SilentlyContinue
}
