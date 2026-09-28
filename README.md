# AI 헬멧 안전 모니터링

## 웹앱 바로 열기

**[웹앱 접속 (이 PC)](http://127.0.0.1:5000)**

또는 GitHub Pages: https://chezooos.github.io/ai-helmet-safety-monitoring/

> 카메라·아두이노·YOLO 서버는 **이 컴퓨터**에서 실행됩니다.  
> Windows 로그인 시 서버가 자동으로 켜지도록 설정되어 있습니다.

## 기능

- YOLO 헬멧/조끼 실시간 감지
- Flask + 웹 대시보드
- 아두이노 서보 수동 회전
- 공기질(시뮬레이션) 표시

## 실행 (수동)

```powershell
cd C:\Users\COM\Desktop\lg
py app.py
```

브라우저: http://127.0.0.1:5000

## 자동 시작

`scripts\install_autostart.ps1` 을 관리자 권한으로 한 번 실행하면  
Windows 로그인 시 서버가 자동 기동합니다.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\COM\Desktop\lg\scripts\install_autostart.ps1
```
