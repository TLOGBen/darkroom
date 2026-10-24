# Run every check of hypothesis photo-edit with TLC and print one line per config:
#   <config>: states=<distinct states> steps=<counterexample length> <TLC verdict line>
# Usage: pwsh -File model/check.ps1 [-Jar <tla2tools.jar>]   (env TLA2TOOLS_JAR also works)
param(
    [string]$Jar = $(if ($env:TLA2TOOLS_JAR) { $env:TLA2TOOLS_JAR } else { 'D:\Workspace\00_Env\tla\tla2tools.jar' }),
    [string[]]$Configs = @('model/PhotoEdit.cfg', 'model/Goal.cfg', 'variants/G1-NoRestore.cfg',
                           'variants/R1-Unlocked.cfg', 'variants/R2-Unlocked.cfg')
)
$ErrorActionPreference = 'Stop'
$model = $PSScriptRoot
$area = Split-Path $model -Parent
$meta = Join-Path ([System.IO.Path]::GetTempPath()) ("tlc-photo-edit-" + [guid]::NewGuid().ToString('N'))
Push-Location $model
try {
    foreach ($c in $Configs) {
        $cfg = Join-Path $area $c
        $out = & java -XX:+UseParallelGC -cp $Jar tlc2.TLC -nowarning -deadlock -config $cfg -metadir (Join-Path $meta ($c -replace '[\/.]', '-')) PhotoEdit.tla 2>&1 | Out-String
        $states = ([regex]::Matches($out, '([\d,]+) distinct states found') | Select-Object -Last 1).Groups[1].Value -replace ',', ''
        $steps = ([regex]::Matches($out, '(?m)^State \d+:')).Count
        $verdict = ([regex]::Match($out, '(?m)^(Error: Invariant \w+ is violated\.|Model checking completed\. No error has been found\.)')).Value
        "${c}: states=$states steps=$steps $verdict"
    }
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $meta -ErrorAction SilentlyContinue
}
