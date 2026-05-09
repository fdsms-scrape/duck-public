param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DuckbotArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptRoot

$pythonCandidates = @(
    (Join-Path $scriptRoot ".venv\\Scripts\\python.exe"),
    (Join-Path $scriptRoot "venv\\Scripts\\python.exe"),
    "python"
)

$pythonExecutable = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python") {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) {
            $pythonExecutable = $command.Source
            break
        }
        continue
    }

    if (Test-Path $candidate) {
        $pythonExecutable = $candidate
        break
    }
}

if (-not $pythonExecutable) {
    throw "Не удалось найти Python. Установите Python или создайте .venv."
}

$arguments = if ($null -ne $DuckbotArgs -and $DuckbotArgs.Length -gt 0) {
    @($DuckbotArgs)
}
else {
    @("run", "--all")
}

$process = Start-Process `
    -FilePath $pythonExecutable `
    -ArgumentList (@("-m", "duckbot") + $arguments) `
    -NoNewWindow `
    -Wait `
    -PassThru

exit $process.ExitCode
