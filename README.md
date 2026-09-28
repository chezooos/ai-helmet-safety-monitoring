# AI 헬멧 안전 모니터링

## 웹앱

배포 URL은 Cloud Run 배포 후 README에 갱신됩니다.

로컬: http://127.0.0.1:5000

```powershell
cd C:\Users\COM\Desktop\lg
py app.py
```

## GCP Cloud Run 배포

```bash
gcloud run deploy ai-helmet-safety \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars ARDUINO_ENABLED=0
```

카메라/아두이노는 클라우드에 없어서 감지·서보는 로컬 PC에서 쓰는 기능입니다.
클라우드에서는 UI·공기질 시뮬레이션·API가 상시 제공됩니다.
