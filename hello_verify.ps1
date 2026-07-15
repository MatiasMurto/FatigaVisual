param([string]$Mensaje = "Confirma tu identidad")

# Invoca Windows Hello (UserConsentVerifier) via WinRT y devuelve el resultado
# por stdout como "RESULT:<estado>" o "ERROR:<mensaje>".
$ErrorActionPreference = "Stop"
try {
    $null = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, ContentType = WindowsRuntime]
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]

    function Await($op, $t) {
        $m    = $asTaskGeneric.MakeGenericMethod($t)
        $task = $m.Invoke($null, @($op))
        $task.Wait(-1) | Out-Null
        $task.Result
    }

    $availType = [Windows.Security.Credentials.UI.UserConsentVerifierAvailability]
    $avail = Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::CheckAvailabilityAsync()) $availType
    if ($avail -ne 'Available') {
        Write-Output "UNAVAILABLE:$avail"
        exit 0
    }

    $resType = [Windows.Security.Credentials.UI.UserConsentVerificationResult]
    $res = Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::RequestVerificationAsync($Mensaje)) $resType
    Write-Output "RESULT:$res"
}
catch {
    Write-Output "ERROR:$($_.Exception.Message)"
}
