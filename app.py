from flask import Flask, Response, jsonify, send_from_directory, request
from ultralytics import YOLO
import cv2
import time
import threading
import os
import random
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

app = Flask(__name__, static_folder=".", static_url_path="")

MODEL_CANDIDATES = [
    Path("models/best.pt"),
    Path(r"C:\Users\COM\runs\detect\runs\detect\helmet_yolo11_clean\weights\best.pt"),
    Path("runs/detect/helmet_yolo11_clean/weights/best.pt"),
    Path("runs/detect/train/weights/best.pt"),
    Path("runs/detect/helmet_yolo11/weights/best.pt"),
]

# no_helmet 은 점수가 낮은 편이라 기본 임계값을 낮게 둠
DETECT_CONF = 0.2
CLASS_CONF = {
    "no_helmet": 0.05,
    "helmet": 0.05,
    "no_vest": 0.08,
    "person": 0.08,
    "vest": 0.08,
}
DISPLAY_NAMES = {
    "no_helmet": "미착용",
    "helmet": "헬멧",
    "no_vest": "조끼미착용",
    "person": "사람",
    "vest": "안전조끼",
}

# 사람 박스 확장 (머리·어깨 장비 매칭용)
PERSON_EXPAND_UP = 0.55
PERSON_EXPAND_SIDE = 0.18
PERSON_EXPAND_DOWN = 0.20
# 조끼만 잡혔을 때 합성 사람 박스 (위로 머리 영역 확보)
SYNTH_EXPAND_UP = 1.5
SYNTH_EXPAND_SIDE = 0.40
SYNTH_EXPAND_DOWN = 0.25
# 장비 박스 중심이 사람 박스 안에 있으면 매칭
GEAR_CENTER_MARGIN = 0.08
# 헬멧/조끼 깜빡임 완화 (프레임 유지)
PPE_HOLD_FRAMES = 18


model = None
cap = None
detecting = False
camera_lock = threading.Lock()
stats_lock = threading.Lock()
servo_lock = threading.Lock()

# 아두이노 서보 (기본 COM5, 환경변수 ARDUINO_PORT 로 변경 가능)
ARDUINO_PORT = os.environ.get("ARDUINO_PORT", "COM5")
ARDUINO_BAUD = int(os.environ.get("ARDUINO_BAUD", "115200"))
servo_serial = None
servo_angle = 90
servo_manual_until = 0.0  # 수동 조작 후 잠시 자동추적 중지
SERVO_MANUAL_HOLD_SEC = 3.0
TRACK_DEADZONE = 0.10      # 화면 중앙 기준 ±10% 이내면 유지
TRACK_GAIN = 18.0          # 추적 보정 (너무 크면 덜컹거림)
TRACK_MIN_INTERVAL = 0.20
SERVO_SEND_MIN_INTERVAL = 0.10
SERVO_MAX_STEP = 4         # 한 번에 최대 이동 각도 (부드러움)
SCAN_STEP_DEG = 2          # 탐색 시 한 스텝
SCAN_INTERVAL_SEC = 0.18   # 탐색 간격 (연속적으로 천천히)
SCAN_MIN_ANGLE = 0
SCAN_MAX_ANGLE = 180
# 90° 넘어가면 더 천천히 (기구/부하 때문에 덜컹대기 쉬움)
SCAN_STEP_OVER_90 = 1
SCAN_INTERVAL_OVER_90 = 0.28
last_track_send = 0.0
last_servo_send = 0.0
scan_direction = 1         # 1: 각도 증가, -1: 감소
last_scan_move = 0.0
ppe_hold = {"helmet": 0, "vest": 0, "no_helmet": 0, "no_vest": 0}

session_detect_count = 0
latest_stats = {
    "detect_count": 0,
    "no_helmet_count": 0,
    "person_count": 0,
    "helmet_count": 0,
    "air_quality_ppm": 350,
    "detecting": False,
    "camera_ok": False,
    "message": "",
    "servo_angle": 90,
    "servo_connected": False,
    "servo_mode": "center",
}
recent_logs = []
MAX_LOGS = 20

AIR_SIM_MIN = 300
AIR_SIM_MAX = 400
AIR_SIM_INTERVAL_SEC = 1.2
_air_sim_thread = None
_air_sim_stop = threading.Event()


def simulate_air_quality_loop():
    """현재 공기질을 300~400 사이에서 자연스럽게 오가게 시뮬레이션."""
    ppm = random.randint(AIR_SIM_MIN, AIR_SIM_MAX)
    with stats_lock:
        latest_stats["air_quality_ppm"] = ppm

    while not _air_sim_stop.is_set():
        # -15 ~ +15 랜덤 워크, 범위 밖으로 안 나가게 클램프
        delta = random.randint(-15, 15)
        ppm = max(AIR_SIM_MIN, min(AIR_SIM_MAX, ppm + delta))
        with stats_lock:
            latest_stats["air_quality_ppm"] = float(ppm)
        _air_sim_stop.wait(AIR_SIM_INTERVAL_SEC)


def start_air_quality_simulation():
    global _air_sim_thread
    if _air_sim_thread is not None and _air_sim_thread.is_alive():
        return
    _air_sim_stop.clear()
    _air_sim_thread = threading.Thread(
        target=simulate_air_quality_loop,
        name="air-sim",
        daemon=True,
    )
    _air_sim_thread.start()
    print(f"공기질 시뮬레이션 시작: {AIR_SIM_MIN}~{AIR_SIM_MAX} ppm")


def open_servo_serial():
    """아두이노 시리얼 연결 (COM5 기본)."""
    global servo_serial
    if serial is None:
        print("pyserial 미설치: pip install pyserial")
        return False

    with servo_lock:
        if servo_serial is not None and getattr(servo_serial, "is_open", False):
            return True

        ports_to_try = [ARDUINO_PORT]
        if list_ports is not None:
            for p in list_ports.comports():
                if p.device not in ports_to_try:
                    ports_to_try.append(p.device)

        for port in ports_to_try:
            try:
                ser = serial.Serial(port, ARDUINO_BAUD, timeout=0.3, write_timeout=1.0)
                time.sleep(2.0)  # 아두이노 리셋 대기
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                ser.write(b"C\n")
                ser.flush()
                servo_serial = ser
                print(f"아두이노 연결: {port}")
                with stats_lock:
                    latest_stats["servo_connected"] = True
                    latest_stats["servo_angle"] = 90
                return True
            except Exception as e:
                print(f"아두이노 연결 실패 ({port}): {e}")

        servo_serial = None
        with stats_lock:
            latest_stats["servo_connected"] = False
        return False


def close_servo_serial():
    global servo_serial
    with servo_lock:
        if servo_serial is not None:
            try:
                servo_serial.close()
            except Exception:
                pass
            servo_serial = None
    with stats_lock:
        latest_stats["servo_connected"] = False


def send_servo_angle(angle, manual=False):
    """서보 각도 전송. 한 번에 큰 점프를 막아 덜컹거림 감소."""
    global servo_angle, servo_manual_until, last_track_send, last_servo_send, servo_serial

    angle = int(max(0, min(180, round(angle))))
    now = time.time()

    # 자동 모드에서는 큰 각도 점프를 나눠서 이동
    if not manual and abs(angle - servo_angle) > SERVO_MAX_STEP:
        angle = servo_angle + SERVO_MAX_STEP if angle > servo_angle else servo_angle - SERVO_MAX_STEP

    with servo_lock:
        if servo_serial is None or not getattr(servo_serial, "is_open", False):
            servo_angle = angle
            with stats_lock:
                latest_stats["servo_angle"] = angle
            return False

        if abs(angle - servo_angle) < 1:
            if manual:
                servo_manual_until = now + SERVO_MANUAL_HOLD_SEC
            return True
        if (now - last_servo_send) < SERVO_SEND_MIN_INTERVAL and not manual:
            return True

        try:
            if servo_serial.in_waiting:
                servo_serial.reset_input_buffer()
            servo_serial.write(f"A:{angle}\n".encode("ascii"))
            servo_serial.flush()
            servo_angle = angle
            last_track_send = now
            last_servo_send = now
            if manual:
                servo_manual_until = now + SERVO_MANUAL_HOLD_SEC
            with stats_lock:
                latest_stats["servo_angle"] = angle
                latest_stats["servo_connected"] = True
                latest_stats["servo_mode"] = "manual" if manual else latest_stats.get("servo_mode", "auto")
            return True
        except Exception as e:
            print(f"서보 전송 실패: {e}")
            try:
                servo_serial.close()
            except Exception:
                pass
            servo_serial = None
            with stats_lock:
                latest_stats["servo_connected"] = False
            return False


def track_unsafe_person(people, frame_width):
    """자동 서보 회전은 비활성화. 웹 수동 조절(/api/servo)만 사용."""
    with stats_lock:
        if time.time() < servo_manual_until:
            latest_stats["servo_mode"] = "manual"
        else:
            latest_stats["servo_mode"] = "manual_only"
    return


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    if origin:
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


def load_model():
    global model
    for path in MODEL_CANDIDATES:
        if path.exists():
            model = YOLO(str(path))
            print(f"모델 로드: {path}")
            return
    model = YOLO("yolo11n.pt")
    print("학습 모델이 없어 yolo11n.pt 를 사용합니다.")


def open_camera():
    global cap
    with camera_lock:
        if cap is not None and cap.isOpened():
            return True
        if cap is not None:
            cap.release()
            cap = None

        backends = [cv2.CAP_DSHOW, cv2.CAP_ANY]
        for index in (0, 1):
            for backend in backends:
                candidate = cv2.VideoCapture(index, backend)
                if candidate.isOpened():
                    candidate.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    cap = candidate
                    print(f"카메라 연결 성공 (index={index}, backend={backend})")
                    return True
                candidate.release()

        print("카메라를 열 수 없습니다.")
        return False


def close_camera():
    global cap
    with camera_lock:
        if cap is not None:
            cap.release()
            cap = None


def normalize_name(name):
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def is_helmet(name):
    n = normalize_name(name)
    if n.startswith("no_"):
        return False
    return n == "helmet" or n.endswith("_helmet")


def is_no_helmet(name):
    n = normalize_name(name)
    return n in {"no_helmet", "head"} or n.startswith("no_helmet")


def class_label(name):
    if is_no_helmet(name):
        return "미착용"
    if is_helmet(name):
        return "헬멧"
    if is_person(name):
        return "사람"
    if is_vest(name):
        return "안전조끼"
    if is_no_vest(name):
        return "조끼미착용"
    return name


def is_vest(name):
    n = normalize_name(name)
    return n == "vest" or (n.endswith("_vest") and not n.startswith("no_"))


def is_no_vest(name):
    n = normalize_name(name)
    return n in {"no_vest"} or n.startswith("no_vest")


def is_person(name):
    return normalize_name(name) == "person"


def xyxy_of(box):
    return [float(v) for v in box.xyxy[0].tolist()]


def expand_box(xyxy, up=0.0, side=0.0, down=0.0):
    x1, y1, x2, y2 = xyxy
    w = max(1.0, x2 - x1)
    h = max(1.0, y2 - y1)
    return [
        x1 - w * side,
        y1 - h * up,
        x2 + w * side,
        y2 + h * down,
    ]


def box_center(xyxy):
    x1, y1, x2, y2 = xyxy
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def center_inside(inner_xyxy, outer_xyxy, margin=GEAR_CENTER_MARGIN):
    ox1, oy1, ox2, oy2 = expand_box(outer_xyxy, up=margin, side=margin, down=margin)
    cx, cy = box_center(inner_xyxy)
    return ox1 <= cx <= ox2 and oy1 <= cy <= oy2


def box_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def boxes_close(a, b, iou_thr=0.05, dist_thr=None):
    if box_iou(a, b) >= iou_thr:
        return True
    acx, acy = box_center(a)
    bcx, bcy = box_center(b)
    aw, ah = max(1.0, a[2] - a[0]), max(1.0, a[3] - a[1])
    bw, bh = max(1.0, b[2] - b[0]), max(1.0, b[3] - b[1])
    thr = dist_thr if dist_thr is not None else max(aw, ah, bw, bh) * 1.2
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5 <= thr


def extract_detections(result):
    dets = []
    if result.boxes is None or len(result.boxes) == 0:
        return dets
    for box in result.boxes:
        name = model.names[int(box.cls[0])]
        dets.append({
            "name": name,
            "conf": float(box.conf[0]),
            "xyxy": xyxy_of(box),
        })
    return dets


def union_boxes(boxes):
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def synthesize_persons_from_gear(gears):
    """사람 박스가 없을 때 헬멧/조끼 박스로 사람 영역을 만듦."""
    if not gears:
        return []

    used = [False] * len(gears)
    clusters = []
    for i, gear in enumerate(gears):
        if used[i]:
            continue
        group = [gear]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, other in enumerate(gears):
                if used[j]:
                    continue
                if any(boxes_close(g["xyxy"], other["xyxy"]) for g in group):
                    group.append(other)
                    used[j] = True
                    changed = True
        clusters.append(group)

    persons = []
    for group in clusters:
        base = union_boxes([g["xyxy"] for g in group])
        # 조끼만 있으면 위로 크게 확장해 머리(헬멧) 영역 확보
        xyxy = expand_box(
            base,
            up=SYNTH_EXPAND_UP,
            side=SYNTH_EXPAND_SIDE,
            down=SYNTH_EXPAND_DOWN,
        )
        persons.append({
            "name": "person",
            "conf": max(g["conf"] for g in group),
            "xyxy": xyxy,
            "synthetic": True,
        })
    return persons


def build_person_entry(person, gears):
    region = expand_box(
        person["xyxy"],
        up=PERSON_EXPAND_UP,
        side=PERSON_EXPAND_SIDE,
        down=PERSON_EXPAND_DOWN,
    )
    matched = [g for g in gears if center_inside(g["xyxy"], region)]

    has_helmet = any(is_helmet(g["name"]) for g in matched)
    has_no_helmet = any(is_no_helmet(g["name"]) for g in matched)
    has_vest = any(is_vest(g["name"]) for g in matched)
    has_no_vest = any(is_no_vest(g["name"]) for g in matched)

    if has_helmet:
        helmet_status = "착용"
    else:
        # 조끼만 있어도 / 사람만 있어도 헬멧 없으면 미착용
        helmet_status = "미착용"

    if has_vest:
        vest_status = "착용"
    elif has_no_vest:
        vest_status = "미착용"
    else:
        vest_status = "확인중"

    return {
        "xyxy": person["xyxy"],
        "conf": person["conf"],
        "synthetic": bool(person.get("synthetic")),
        "has_helmet": has_helmet,
        "has_no_helmet": has_no_helmet,
        "has_vest": has_vest,
        "has_no_vest": has_no_vest,
        "helmet_status": helmet_status,
        "vest_status": vest_status,
        "matched": matched,
    }


def merge_detections(base, extra):
    """같은 클래스·비슷한 위치 박스는 높은 점수만 남기고 합친다."""
    merged = [dict(d) for d in base]
    for e in extra:
        dup = False
        for b in merged:
            if normalize_name(b["name"]) != normalize_name(e["name"]):
                continue
            if box_iou(b["xyxy"], e["xyxy"]) >= 0.4:
                if e["conf"] > b["conf"]:
                    b["conf"] = e["conf"]
                    b["xyxy"] = e["xyxy"]
                dup = True
                break
        if not dup:
            merged.append(dict(e))
    return merged


def clamp_xyxy(xyxy, width, height):
    x1, y1, x2, y2 = xyxy
    return [
        max(0.0, min(width - 1.0, x1)),
        max(0.0, min(height - 1.0, y1)),
        max(0.0, min(width - 1.0, x2)),
        max(0.0, min(height - 1.0, y2)),
    ]


def detect_on_classes(frame, classes, conf=0.04, imgsz=640):
    result = model(
        frame,
        conf=conf,
        classes=classes,
        verbose=False,
        imgsz=imgsz,
        iou=0.85,
        agnostic_nms=False,
        max_det=50,
    )[0]
    result = filter_boxes_by_class_conf(result)
    return extract_detections(result)


def detect_helmet_above_vest(frame, vest_dets):
    """조끼 박스 위쪽(머리 영역)을 잘라 헬멧을 따로 찾는다."""
    if not vest_dets:
        return []

    height, width = frame.shape[:2]
    extras = []
    for vest in vest_dets:
        x1, y1, x2, y2 = vest["xyxy"]
        vw = max(1.0, x2 - x1)
        vh = max(1.0, y2 - y1)
        # 조끼 위로 머리/헬멧 영역 ROI
        roi = clamp_xyxy(
            [
                x1 - vw * 0.45,
                y1 - vh * 1.6,
                x2 + vw * 0.45,
                y1 + vh * 0.25,
            ],
            width,
            height,
        )
        rx1, ry1, rx2, ry2 = [int(v) for v in roi]
        if rx2 - rx1 < 24 or ry2 - ry1 < 24:
            continue

        crop = frame[ry1:ry2, rx1:rx2]
        if crop.size == 0:
            continue

        # 크롭은 작게 확대해서 추론 (부분 헬멧에도 유리)
        head_dets = detect_on_classes(crop, classes=[0, 1], conf=0.03, imgsz=320)
        for d in head_dets:
            bx1, by1, bx2, by2 = d["xyxy"]
            extras.append({
                "name": d["name"],
                "conf": d["conf"],
                "xyxy": [bx1 + rx1, by1 + ry1, bx2 + rx1, by2 + ry1],
            })
    return extras


def detect_vest_below_helmet(frame, helmet_dets):
    """헬멧 박스 아래(몸통 영역)를 잘라 조끼를 따로 찾는다."""
    if not helmet_dets:
        return []

    height, width = frame.shape[:2]
    extras = []
    for helmet in helmet_dets:
        x1, y1, x2, y2 = helmet["xyxy"]
        hw = max(1.0, x2 - x1)
        hh = max(1.0, y2 - y1)
        roi = clamp_xyxy(
            [
                x1 - hw * 1.2,
                y2 - hh * 0.2,
                x2 + hw * 1.2,
                y2 + hh * 3.5,
            ],
            width,
            height,
        )
        rx1, ry1, rx2, ry2 = [int(v) for v in roi]
        if rx2 - rx1 < 24 or ry2 - ry1 < 24:
            continue

        crop = frame[ry1:ry2, rx1:rx2]
        if crop.size == 0:
            continue

        body_dets = detect_on_classes(crop, classes=[2, 3, 4], conf=0.03, imgsz=320)
        for d in body_dets:
            bx1, by1, bx2, by2 = d["xyxy"]
            extras.append({
                "name": d["name"],
                "conf": d["conf"],
                "xyxy": [bx1 + rx1, by1 + ry1, bx2 + rx1, by2 + ry1],
            })
    return extras


def run_detection(frame):
    """
    헬멧+조끼가 한 화면에 같이 나오도록:
    1) 전체 추론
    2) 헬멧/조끼 클래스 전용 추론 병합
    3) 조끼만 있으면 머리 ROI, 헬멧만 있으면 몸통 ROI 재탐색
    """
    r_main = model(
        frame,
        conf=0.04,
        verbose=False,
        imgsz=640,
        iou=0.85,
        agnostic_nms=False,
        max_det=100,
    )[0]
    r_main = filter_boxes_by_class_conf(r_main)
    dets = extract_detections(r_main)

    # 매 프레임 헬멧·조끼 전용 패스 (서로 눌러지지 않게)
    dets = merge_detections(dets, detect_on_classes(frame, classes=[0, 1], conf=0.04))
    dets = merge_detections(dets, detect_on_classes(frame, classes=[2, 4], conf=0.04))
    dets = merge_detections(dets, detect_on_classes(frame, classes=[3], conf=0.05))

    vest_dets = [d for d in dets if is_vest(d["name"]) or is_no_vest(d["name"])]
    helmet_dets = [d for d in dets if is_helmet(d["name"]) or is_no_helmet(d["name"])]

    # 조끼는 있는데 헬멧이 없으면 조끼 위쪽을 확대해서 재탐색
    if vest_dets and not any(is_helmet(d["name"]) for d in helmet_dets):
        dets = merge_detections(dets, detect_helmet_above_vest(frame, vest_dets))

    # 헬멧은 있는데 조끼 판정이 없으면 아래쪽 재탐색
    helmet_only = [d for d in dets if is_helmet(d["name"]) or is_no_helmet(d["name"])]
    vest_after = [d for d in dets if is_vest(d["name"]) or is_no_vest(d["name"])]
    if helmet_only and not vest_after:
        dets = merge_detections(dets, detect_vest_below_helmet(frame, helmet_only))

    return dets, r_main


def stabilize_ppe(people):
    """짧은 프레임 동안 헬멧/조끼 인식이 사라져도 유지 (동시 착용 깜빡임 방지)."""
    global ppe_hold

    any_helmet = any(p["has_helmet"] for p in people)
    any_vest = any(p["has_vest"] for p in people)
    any_no_helmet = any(p["has_no_helmet"] for p in people)
    any_no_vest = any(p["has_no_vest"] for p in people)

    if any_helmet:
        ppe_hold["helmet"] = PPE_HOLD_FRAMES
    elif ppe_hold["helmet"] > 0:
        ppe_hold["helmet"] -= 1

    if any_vest:
        ppe_hold["vest"] = PPE_HOLD_FRAMES
    elif ppe_hold["vest"] > 0:
        ppe_hold["vest"] -= 1

    if any_no_helmet:
        ppe_hold["no_helmet"] = PPE_HOLD_FRAMES
    elif ppe_hold["no_helmet"] > 0:
        ppe_hold["no_helmet"] -= 1

    if any_no_vest:
        ppe_hold["no_vest"] = PPE_HOLD_FRAMES
    elif ppe_hold["no_vest"] > 0:
        ppe_hold["no_vest"] -= 1

    for p in people:
        # 조끼가 보이는 사람(또는 합성)에게 최근 헬멧 유지
        if not p["has_helmet"] and ppe_hold["helmet"] > 0 and (p["has_vest"] or p["has_no_vest"] or p.get("synthetic")):
            if ppe_hold["no_helmet"] <= 0:
                p["has_helmet"] = True
                p["helmet_status"] = "착용"
        if not p["has_vest"] and ppe_hold["vest"] > 0 and (p["has_helmet"] or p["has_no_helmet"] or p.get("synthetic")):
            if ppe_hold["no_vest"] <= 0:
                p["has_vest"] = True
                p["vest_status"] = "착용"
        if p["has_helmet"]:
            p["helmet_status"] = "착용"
        elif p["has_no_helmet"] or ppe_hold["no_helmet"] > 0:
            p["helmet_status"] = "미착용"
        if p["has_vest"]:
            p["vest_status"] = "착용"
        elif p["has_no_vest"] or ppe_hold["no_vest"] > 0:
            p["vest_status"] = "미착용"
    return people


def draw_detections(frame, detections):
    """병합된 헬멧/조끼 박스도 화면에 표시."""
    frame = frame.copy()
    palette = {
        "helmet": (255, 180, 0),
        "no_helmet": (0, 0, 255),
        "vest": (0, 200, 255),
        "no_vest": (80, 80, 255),
        "person": (0, 220, 0),
    }
    for d in detections:
        name = normalize_name(d["name"])
        x1, y1, x2, y2 = [int(v) for v in d["xyxy"]]
        color = palette.get(name, (200, 200, 200))
        label = f"{DISPLAY_NAMES.get(name, d['name'])} {d['conf']:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame, label, (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA,
        )
    return frame


def associate_ppe(detections):
    """사람 박스 안에 들어온 헬멧/조끼만 그 사람에게 연결.
    사람 박스가 없어도 조끼/헬멧이 있으면 합성 사람 박스로 판정.
    """
    persons = [d for d in detections if is_person(d["name"])]
    gears = [d for d in detections if not is_person(d["name"])]

    # 조끼만 강하게 잡혀 사람이 빠진 경우 보정
    if not persons and gears:
        persons = synthesize_persons_from_gear(gears)
    else:
        # 사람 밖에 남은 장비도 별도 사람으로 보정
        unmatched = []
        for gear in gears:
            claimed = False
            for person in persons:
                region = expand_box(
                    person["xyxy"],
                    up=PERSON_EXPAND_UP,
                    side=PERSON_EXPAND_SIDE,
                    down=PERSON_EXPAND_DOWN,
                )
                if center_inside(gear["xyxy"], region):
                    claimed = True
                    break
            if not claimed:
                unmatched.append(gear)
        if unmatched:
            persons = persons + synthesize_persons_from_gear(unmatched)

    return [build_person_entry(person, gears) for person in persons]


def draw_person_status(frame, people):
    """사람 박스에 헬멧/조끼 상태 표시."""
    frame = frame.copy()
    for person in people:
        x1, y1, x2, y2 = [int(v) for v in person["xyxy"]]
        unsafe = person["helmet_status"] == "미착용" or person["vest_status"] == "미착용"
        color = (0, 0, 255) if unsafe else (0, 180, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        en = (
            f"H:{'OK' if person['helmet_status'] == '착용' else 'NO'} "
            f"V:{'OK' if person['vest_status'] == '착용' else ('NO' if person['vest_status'] == '미착용' else '?')}"
        )
        cv2.putText(
            frame, en, (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA,
        )
    return frame


def filter_boxes_by_class_conf(result):
    """클래스별 신뢰도 기준으로 박스 필터링."""
    if result.boxes is None or len(result.boxes) == 0:
        return result

    keep = []
    for i, box in enumerate(result.boxes):
        name = normalize_name(model.names[int(box.cls[0])])
        conf = float(box.conf[0])
        threshold = CLASS_CONF.get(name, DETECT_CONF)
        if conf >= threshold:
            keep.append(i)

    if len(keep) == len(result.boxes):
        return result
    if not keep:
        result.boxes = result.boxes[:0]
        return result
    result.boxes = result.boxes[keep]
    return result


def plot_korean(result):
    """화면 박스 라벨을 한글로 표시."""
    original = dict(getattr(result, "names", {}) or model.names)
    result.names = {i: DISPLAY_NAMES.get(n, n) for i, n in original.items()}
    try:
        return result.plot()
    finally:
        result.names = original


def update_detection_stats(result, people):
    global session_detect_count, recent_logs

    detections = extract_detections(result)
    names = [d["name"] for d in detections]
    confidences = [d["conf"] for d in detections]

    person_count = len(people)
    helmet_count = sum(1 for p in people if p["has_helmet"])
    vest_count = sum(1 for p in people if p["has_vest"])
    no_helmet_count = sum(1 for p in people if p["helmet_status"] == "미착용")
    no_vest_count = sum(1 for p in people if p["vest_status"] == "미착용")

    if people:
        session_detect_count += 1
        # 가장 위험한 사람을 로그에 우선 기록
        focus = next((p for p in people if p["helmet_status"] == "미착용"), people[0])
        gear_conf = 0.0
        if focus["matched"]:
            gear_conf = max(g["conf"] for g in focus["matched"])
        else:
            gear_conf = focus["conf"]

        log_row = {
            "time": time.strftime("%H:%M:%S"),
            "target": "사람",
            "helmet": focus["helmet_status"],
            "air": "양호" if latest_stats["air_quality_ppm"] < 1000 else "초과",
            "confidence": f"{gear_conf * 100:.1f}%",
        }
        with stats_lock:
            recent_logs.insert(0, log_row)
            recent_logs[:] = recent_logs[:MAX_LOGS]
    elif names:
        session_detect_count += 1

    with stats_lock:
        latest_stats.update({
            "detect_count": session_detect_count,
            "no_helmet_count": no_helmet_count,
            "person_count": person_count,
            "helmet_count": helmet_count,
            "vest_count": vest_count,
            "no_vest_count": no_vest_count,
            "detecting": detecting,
            "camera_ok": cap is not None and cap.isOpened(),
            "detected": [class_label(n) for n in names],
        })


def generate_frames():
    global detecting

    while detecting:
        with camera_lock:
            if cap is None or not cap.isOpened():
                break
            ok, frame = cap.read()

        if not ok:
            time.sleep(0.05)
            continue

        # 낮은 임계값 + 헬멧/조끼 2패스 병합
        detections, result = run_detection(frame)
        people = associate_ppe(detections)
        people = stabilize_ppe(people)

        result_frame = draw_detections(frame, detections)
        result_frame = draw_person_status(result_frame, people)
        update_detection_stats(result, people)
        # status의 detected 는 병합 결과 기준으로 덮어씀
        with stats_lock:
            latest_stats["detected"] = [class_label(d["name"]) for d in detections]
            latest_stats["helmet_count"] = sum(1 for p in people if p["has_helmet"])
            latest_stats["vest_count"] = sum(1 for p in people if p["has_vest"])
            latest_stats["no_helmet_count"] = sum(1 for p in people if p["helmet_status"] == "미착용")
        track_unsafe_person(people, result_frame.shape[1])

        ok, buffer = cv2.imencode(".jpg", result_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        )

    with stats_lock:
        latest_stats["detecting"] = False
        latest_stats["no_helmet_count"] = 0
        latest_stats["person_count"] = 0
        latest_stats["helmet_count"] = 0
        latest_stats["vest_count"] = 0
        latest_stats["no_vest_count"] = 0


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/status", methods=["GET", "OPTIONS"])
def api_status():
    if request.method == "OPTIONS":
        return ("", 204)
    with stats_lock:
        payload = dict(latest_stats)
        payload["logs"] = list(recent_logs)
    return jsonify(payload)


@app.route("/api/start", methods=["POST", "OPTIONS"])
def api_start():
    global detecting

    if request.method == "OPTIONS":
        return ("", 204)

    if model is None:
        load_model()

    if not open_camera():
        with stats_lock:
            latest_stats["camera_ok"] = False
            latest_stats["message"] = "카메라를 열 수 없습니다."
        return jsonify({"ok": False, "message": "카메라를 열 수 없습니다."}), 500

    open_servo_serial()  # 없어도 감지는 계속

    detecting = True
    with stats_lock:
        latest_stats["detecting"] = True
        latest_stats["camera_ok"] = True
        latest_stats["message"] = ""
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST", "OPTIONS"])
def api_stop():
    global detecting

    if request.method == "OPTIONS":
        return ("", 204)

    detecting = False
    close_camera()
    # 서보는 연결 유지(수동 회전 가능). 완전 종료 시 close_servo_serial()
    with stats_lock:
        latest_stats["detecting"] = False
        latest_stats["no_helmet_count"] = 0
        latest_stats["person_count"] = 0
        latest_stats["helmet_count"] = 0
        latest_stats["vest_count"] = 0
        latest_stats["no_vest_count"] = 0
        latest_stats["camera_ok"] = False
        latest_stats["message"] = ""
        latest_stats["servo_mode"] = "idle"
    return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST", "OPTIONS"])
def api_reset():
    global session_detect_count, recent_logs

    if request.method == "OPTIONS":
        return ("", 204)

    with stats_lock:
        session_detect_count = 0
        recent_logs = []
        latest_stats["detect_count"] = 0
        latest_stats["no_helmet_count"] = 0
    return jsonify({"ok": True})


@app.route("/api/air", methods=["POST", "OPTIONS"])
def api_air():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    ppm = data.get("air_quality_ppm")
    if ppm is None:
        return jsonify({"ok": False, "message": "air_quality_ppm required"}), 400
    with stats_lock:
        latest_stats["air_quality_ppm"] = float(ppm)
    return jsonify({"ok": True})


@app.route("/api/servo", methods=["GET", "POST", "OPTIONS"])
def api_servo():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.method == "GET":
        open_servo_serial()
        with stats_lock:
            return jsonify({
                "ok": True,
                "angle": latest_stats.get("servo_angle", servo_angle),
                "connected": latest_stats.get("servo_connected", False),
                "port": ARDUINO_PORT,
                "mode": latest_stats.get("servo_mode", "idle"),
            })

    data = request.get_json(silent=True) or {}
    if "angle" not in data:
        return jsonify({"ok": False, "message": "angle required"}), 400

    open_servo_serial()
    angle = float(data["angle"])
    ok = send_servo_angle(angle, manual=True)
    return jsonify({
        "ok": True,
        "sent": ok,
        "angle": servo_angle,
        "connected": latest_stats.get("servo_connected", False),
    })


@app.route("/video_feed")
def video_feed():
    if not detecting:
        return jsonify({"ok": False, "message": "감지가 시작되지 않았습니다."}), 400
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    load_model()
    start_air_quality_simulation()
    open_servo_serial()
    print("서버 시작: http://127.0.0.1:5000")
    print(f"아두이노 포트 설정: {ARDUINO_PORT} (환경변수 ARDUINO_PORT 로 변경)")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    finally:
        _air_sim_stop.set()
        close_servo_serial()
