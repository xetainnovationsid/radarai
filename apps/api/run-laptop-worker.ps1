$ErrorActionPreference = "Stop"
$apiDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workerEnv = Join-Path $apiDir ".env.worker"
$python = Join-Path $apiDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

if (-not (Test-Path -LiteralPath $workerEnv)) {
    throw "Copy .env.worker.example to .env.worker and fill in RADAR_WORKER_TOKEN first."
}

$checkpoint = Join-Path $apiDir "data\model-artifacts\ct-binary-densenet121.pt"
if (-not (Test-Path -LiteralPath $checkpoint)) {
    throw "DenseNet121 checkpoint is missing: $checkpoint"
}

& $python -c "import torch, torchvision, httpx, fastapi, pydicom, nibabel, einops; assert torch.cuda.is_available(), 'CUDA is not available'; print('GPU ready:', torch.cuda.get_device_name(0)); print('torch:', torch.__version__, 'torchvision:', torchvision.__version__); print('SAMIHS deps ready')"
if ($LASTEXITCODE -ne 0) { throw "Python inference dependencies are not ready." }

& $python (Join-Path $apiDir "scripts\run_laptop_inference_worker.py")
exit $LASTEXITCODE
