from ultralytics import YOLO
import torch

def main():
    if not torch.cuda.is_available():
        print("GPU를 사용할 수 없습니다.")
        return

    print("GPU:", torch.cuda.get_device_name(0))

    model = YOLO("yolo11n.pt")

    model.train(
        data="dataset/data.yaml",
        epochs=50,
        imgsz=640,
        batch=16,
        device=0,
        workers=4,
        patience=15,
        project="runs/detect",
        name="helmet_yolo11_clean"
    )

if __name__ == "__main__":
    main()