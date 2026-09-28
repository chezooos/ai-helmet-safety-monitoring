/*
  AI 헬멧 모니터링 - 카메라 회전 서보
  - 서보 신호선: 디지털 8번 핀
  - PC(Flask) USB 시리얼 (COM5, 115200)

  명령:
    A:90  /  90  -> 목표 각도
    C           -> 중앙(90)
    ?           -> 현재 각도 응답 OK:xx

  특징:
    - delay로 막지 않음 (명령이 쌓여도 최신 각도만 따라감)
    - 시리얼에 여러 줄이 와도 마지막 명령만 적용
*/

#include <Servo.h>

const int SERVO_PIN = 8;
const int CENTER_ANGLE = 90;
const int MIN_ANGLE = 0;
const int MAX_ANGLE = 180;
const int STEP_MS = 12;   // 1도 이동 간격 (클수록 부드러움, 느림)
const int STEP_MS_OVER_90 = 18;  // 90도 이상에서 더 천천히

Servo cameraServo;
int currentAngle = CENTER_ANGLE;
int targetAngle = CENTER_ANGLE;
unsigned long lastStepMs = 0;
String inputBuffer = "";

void setup() {
  Serial.begin(115200);
  cameraServo.attach(SERVO_PIN);
  currentAngle = CENTER_ANGLE;
  targetAngle = CENTER_ANGLE;
  cameraServo.write(currentAngle);
  Serial.println("READY");
  Serial.print("OK:");
  Serial.println(currentAngle);
}

void loop() {
  readSerialCommands();
  stepTowardTarget();
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        applyCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
      if (inputBuffer.length() > 24) {
        inputBuffer = "";
      }
    }
  }
}

void applyCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  if (cmd.length() == 0) return;

  if (cmd == "?" || cmd == "STATUS") {
    Serial.print("OK:");
    Serial.println(currentAngle);
    return;
  }

  if (cmd == "C" || cmd == "CENTER") {
    targetAngle = CENTER_ANGLE;
    Serial.print("OK:");
    Serial.println(targetAngle);
    return;
  }

  int angle = -1;
  if (cmd.startsWith("A:")) {
    angle = cmd.substring(2).toInt();
  } else {
    // 숫자만 온 경우
    bool digits = true;
    for (unsigned int i = 0; i < cmd.length(); i++) {
      if (!isDigit(cmd.charAt(i))) {
        digits = false;
        break;
      }
    }
    if (digits) {
      angle = cmd.toInt();
    }
  }

  if (angle < MIN_ANGLE || angle > MAX_ANGLE) {
    Serial.println("ERR:ANGLE");
    return;
  }

  targetAngle = angle;  // 최신 목표만 유지
  Serial.print("OK:");
  Serial.println(targetAngle);
}

void stepTowardTarget() {
  if (currentAngle == targetAngle) {
    return;
  }

  unsigned long now = millis();
  unsigned long stepDelay = (currentAngle >= 90 || targetAngle > 90)
      ? (unsigned long)STEP_MS_OVER_90
      : (unsigned long)STEP_MS;
  if (now - lastStepMs < stepDelay) {
    return;
  }
  lastStepMs = now;

  if (currentAngle < targetAngle) {
    currentAngle++;
  } else {
    currentAngle--;
  }
  cameraServo.write(currentAngle);
}
