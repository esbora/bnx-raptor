# Sprecher: lokale Windows-OneCore-Stimme „Microsoft Stefan“ (de-DE), offline. Ein WAV je Satz.
# Aufruf: powershell -File tts_stefan.ps1 <saetze.txt (UTF-8, eine Zeile je Satz)> <ausgabeordner> <rate>
param([string]$Datei, [string]$Ziel, [double]$Rate = 1.0)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$typ) { $t = $asTask.MakeGenericMethod($typ).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$stimme = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -like '*Stefan*' } | Select-Object -First 1
if (-not $stimme) { throw "Stimme Stefan nicht gefunden" }
$synth.Voice = $stimme
$synth.Options.SpeakingRate = $Rate
$synth.Options.AudioPitch = 0.95
New-Item -ItemType Directory -Force $Ziel | Out-Null
$i = 0
foreach ($satz in [IO.File]::ReadAllLines($Datei, [Text.Encoding]::UTF8)) {
    if (-not $satz.Trim()) { continue }
    $i++
    $ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='de-DE'>$satz</speak>"
    $stream = Await ($synth.SynthesizeSsmlToStreamAsync($ssml)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $n = Await ($reader.LoadAsync([uint32]$stream.Size)) ([uint32])
    $bytes = New-Object byte[] $n
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes((Join-Path $Ziel ("satz_{0:D2}.wav" -f $i)), $bytes)
}
Write-Output "Stimme: $($stimme.DisplayName) – $i Sätze"
