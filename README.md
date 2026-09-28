# AI 헬멧 안전 모니터링

## 웹앱 접속 (중간 화면 없음)

**공개 주소:** https://necessarily-close-consumers-genealogy.trycloudflare.com

로컬: http://127.0.0.1:5000

GitHub: https://github.com/chezooos/ai-helmet-safety-monitoring

> PC가 켜져 있고 Flask + 터널이 실행 중이어야 합니다.  
> Windows 시작 시 서버/터널 자동 실행을 걸어 두었습니다.

## GCP Cloud Run

현재 GCP 프로젝트에 **결제(Billing)가 꺼져 있어** Cloud Run API를 켤 수 없습니다.

1. https://console.cloud.google.com/billing 에서 결제 계정 연결  
2. 아래 실행:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\COM\Desktop\lg\scripts\deploy_gcp.ps1
```

클라우드에는 카메라/아두이노가 없어서, 실제 감지·서보는 **이 PC + 공개 터널** 방식이 맞습니다.

## 로컬 실행

```powershell
cd C:\Users\COM\Desktop\lg
py app.py
```
