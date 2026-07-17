$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$settingNames = @(
    "GARAGE_DATABASE_URL",
    "GARAGE_DATABASE_ECHO",
    "GARAGE_LLM_PROVIDER",
    "GARAGE_LLM_BASE_URL",
    "GARAGE_LLM_MODEL",
    "GARAGE_LLM_API_KEY",
    "GARAGE_LLM_API_KEY_FILE",
    "GARAGE_LLM_TIMEOUT_SECONDS",
    "GARAGE_LLM_MAX_RETRIES",
    "GARAGE_LLM_MAX_TOKENS",
    "GARAGE_LLM_TEMPERATURE",
    "GARAGE_LLM_ENABLE_THINKING"
)

foreach ($name in $settingNames) {
    $processValue = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($null -ne $processValue) {
        continue
    }

    $userValue = [Environment]::GetEnvironmentVariable($name, "User")
    if ($null -ne $userValue) {
        [Environment]::SetEnvironmentVariable($name, $userValue, "Process")
    }
}

$executable = Join-Path $repositoryRoot ".venv\Scripts\garage-sales-api.exe"
Push-Location $repositoryRoot
try {
    & $executable
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
