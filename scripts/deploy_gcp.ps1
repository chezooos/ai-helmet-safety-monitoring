# Deploy to Google Cloud Run (asia-northeast3 / Seoul)
$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if (-not (Test-Path $gcloud)) {
    throw "gcloud not found. Install Google Cloud SDK first."
}

Set-Location "C:\Users\COM\Desktop\lg"

Write-Host "Checking auth..."
& $gcloud auth list

$project = & $gcloud config get-value project 2>$null
if (-not $project -or $project -eq "(unset)") {
    Write-Host "No project set. Creating/selecting project..."
    Write-Host "Run: gcloud projects list"
    Write-Host "Then: gcloud config set project YOUR_PROJECT_ID"
    throw "Set a GCP project first"
}

Write-Host "Using project: $project"
& $gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

& $gcloud run deploy ai-helmet-safety `
  --source . `
  --region asia-northeast3 `
  --allow-unauthenticated `
  --memory 2Gi `
  --cpu 2 `
  --timeout 300 `
  --max-instances 2 `
  --set-env-vars "ARDUINO_ENABLED=0,ARDUINO_PORT=" `
  --quiet

$url = & $gcloud run services describe ai-helmet-safety --region asia-northeast3 --format="value(status.url)"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host $url | Set-Content -Path "C:\Users\COM\Desktop\lg\DEPLOY_URL.txt" -Encoding utf8
