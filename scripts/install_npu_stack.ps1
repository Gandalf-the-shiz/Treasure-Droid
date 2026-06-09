# Install Snapdragon / Windows ARM NPU acceleration for ONNX + optional local LLM.
param(
    [switch]$GenAI,
    [switch]$DirectML
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
Set-Location $RepoRoot

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host "[npu] upgrading pip..."
& $Python -m pip install --upgrade pip

Write-Host "[npu] onnxruntime-qnn (Snapdragon NPU)..."
& $Python -m pip install --upgrade onnxruntime-qnn

if ($DirectML) {
    Write-Host "[npu] onnxruntime-directml..."
    & $Python -m pip install --upgrade onnxruntime-directml
}

if ($GenAI) {
    Write-Host "[npu] onnxruntime-genai for local Phi-3..."
    & $Python -m pip install --upgrade onnxruntime-genai
    $modelDir = Join-Path $RepoRoot "models\reasoning"
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    Write-Host "[npu] Download Phi-3 mini to $modelDir (see docs/GLORIOUS_STACK.md)"
}

Write-Host "[npu] probing QNN plugin registration + HTP devices..."
$env:PYTHONPATH = (Join-Path $RepoRoot "scripts")
& $Python "scripts/npu_runtime.py"
& $Python -c @"
import numpy as np
from npu_runtime import create_inference_session, write_status, primary_provider
p = r'$RepoRoot\models\penny\champion.onnx'
import os
if os.path.exists(p):
    s = create_inference_session(p)
    n = len(s.get_inputs()[0].shape) if s.get_inputs()[0].shape else 0
    x = np.zeros((1, int(n or 13)), dtype=np.float32)
    s.run(None, {s.get_inputs()[0].name: x})
    print('[npu] penny champion inference OK:', s.get_providers())
write_status()
print('[npu] primary:', primary_provider())
"@
& $Python "scripts/npu_llm.py" "probe"
