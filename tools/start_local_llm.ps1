<#
.SYNOPSIS
Start a local OpenAI-compatible model server for Melody's interpretation
stage, bound to loopback only.

.DESCRIPTION
Melody's Phase 1 talks to models over 127.0.0.1 and nothing else. This
script starts a llama.cpp-style server with the flags that matter:
loopback bind, a context of at least 32,768 tokens (a half-hour single-pass
prompt runs ~14k in and needs room to answer), and a port matching the
app's default provider_base_url (http://127.0.0.1:8080/v1).

Do not start the server while the transcription pipeline is running on the
same GPU: the pipeline peaks at 11.3 GB during the verbatim pass and a 14B
model at 4-bit wants 9 GB or more of its own. Start it after the batch
finishes, or run it on a second card. docs/LOCAL_MODEL.md has candidates.

.EXAMPLE
.\tools\start_local_llm.ps1 -Server C:\llama\llama-server.exe -Model C:\models\qwen2.5-14b-instruct-q4_k_m.gguf
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Server,

    [Parameter(Mandatory = $true)]
    [string]$Model,

    [int]$Port = 8080,
    [int]$ContextLength = 32768,
    [int]$GpuLayers = 999
)

if (-not (Test-Path $Server)) {
    Write-Error "Server executable not found: $Server"
    exit 1
}
if (-not (Test-Path $Model)) {
    Write-Error "Model file not found: $Model"
    exit 1
}
if ($ContextLength -lt 32768) {
    Write-Warning "Context below 32768 will truncate half-hour calls; raising it."
    $ContextLength = 32768
}

Write-Host "Starting $([System.IO.Path]::GetFileName($Model)) on 127.0.0.1:$Port (context $ContextLength)"
Write-Host "Melody's Settings > Interpretation should read: provider openai_compat, http://127.0.0.1:$Port/v1"

& $Server `
    --host 127.0.0.1 `
    --port $Port `
    --model $Model `
    --ctx-size $ContextLength `
    --n-gpu-layers $GpuLayers
