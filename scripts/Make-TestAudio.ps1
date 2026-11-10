$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'work') -Force | Out-Null
Add-Type -AssemblyName System.Speech
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
$audioFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
try {
    $synthesizer.SetOutputToWaveFile((Join-Path $projectRoot 'work\english-fixture.wav'), $audioFormat)
    $synthesizer.Speak('This video explains how to build a local speech recognition system. Your audio stays on this computer. You can choose English, Chinese, or bilingual subtitles. Existing subtitles are used whenever they are available.')
} finally { $synthesizer.Dispose() }
Write-Host 'Generated original English test audio directly to WAV; no speaker output.'
