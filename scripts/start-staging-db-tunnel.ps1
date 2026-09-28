param(
    [ValidateRange(1024, 65535)][int]$LocalPort = 15432,
    [string]$AwsProfile = 'traceworth-staging'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$previousProfile = $env:AWS_PROFILE
$previousPath = $env:PATH

try {
    $env:AWS_PROFILE = $AwsProfile
    $pluginDirectory = Join-Path $env:ProgramFiles 'Amazon\SessionManagerPlugin\bin'
    if (-not (Get-Command session-manager-plugin -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $pluginDirectory)) {
        $env:PATH = "$pluginDirectory;$env:PATH"
    }
    if (-not (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)) {
        throw 'Install the AWS Session Manager plugin before opening the database tunnel.'
    }

    Push-Location -LiteralPath $repoRoot
    try {
        $instanceId = (& terraform -chdir=infra/staging output -raw db_access_instance_id).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $instanceId -or $instanceId -eq 'null') {
            throw 'The private database access instance is not in the staging Terraform outputs.'
        }
        $dbEndpoint = (& terraform -chdir=infra/staging output -raw database_endpoint).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $dbEndpoint) {
            throw 'The staging database endpoint is not in the Terraform outputs.'
        }
    }
    finally {
        Pop-Location
    }

    Write-Host "Opening localhost:$LocalPort to the private staging database through $instanceId."
    Write-Host 'Keep this terminal open while using pgAdmin; press Ctrl+C to close the tunnel.'
    & aws ssm start-session --profile $AwsProfile --region us-east-2 --target $instanceId --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters "host=$dbEndpoint,portNumber=5432,localPortNumber=$LocalPort"
    if ($LASTEXITCODE -ne 0) { throw 'The Session Manager tunnel failed.' }
}
finally {
    $env:AWS_PROFILE = $previousProfile
    $env:PATH = $previousPath
}
