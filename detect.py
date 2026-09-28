from ultralytics import YOLO
import cv2

# 새로 학습한 YOLO11 모델
model = YOLO(
    r"C:\Users\COM\runs\detect\runs\detect\helmet_yolo11_clean\weights\best.pt"
)

# 기본 카메라
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("카메라를 열 수 없습니다.")
    exit()

print("카메라 실행 성공")
print("종료하려면 Q를 누르세요.")

while True:
    ret, frame = cap.read()

    if not ret:
        print("카메라 영상을 가져오지 못했습니다.")
        break

    # YOLO11 실시간 감지
    results = model(
        frame,
        conf=0.3,
        device=0,
        verbose=False
    )

    # 감지 박스 표시
    result_frame = results[0].plot()

    # 터미널에 감지 결과 출력
    for box in results[0].boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        class_name = model.names[class_id]

        print(
            f"감지: {class_name} / "
            f"신뢰도: {confidence * 100:.1f}%"
        )

    cv2.imshow("YOLO11 Safety Detection", result_frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()