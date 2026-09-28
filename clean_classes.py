from pathlib import Path
import yaml
import shutil

DATASET_DIR = Path("dataset")
YAML_PATH = DATASET_DIR / "data.yaml"

# 기존 클래스 → 새로운 클래스
# None = 해당 라벨 삭제
CLASS_MAP = {
    "helmet": "helmet",
    "person": "person",
    "vest": "vest",

    "no vest": "no_vest",
    "no-vest": "no_vest",

    # head가 '헬멧을 안 쓴 머리'라는 뜻일 때만 이렇게 사용
    "head": "no_helmet",

    # 아래 클래스는 실제 라벨 확인 후 필요 없으면 None
    "belt": None,
    "0": None,
    "object": None,

    # 실제로 helmet 라벨이라면 "helmet"으로 변경
    "safety_helmet_detection_0321 - v3 2024-03-27 8-32pm": "helmet",
}


# data.yaml 읽기
with open(YAML_PATH, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

old_names = data["names"]

# dict 형태일 경우 list로 변환
if isinstance(old_names, dict):
    old_names = [old_names[i] for i in sorted(old_names)]

print("기존 클래스:")
for i, name in enumerate(old_names):
    print(i, name)


# 사용할 새로운 클래스 목록
new_names = []

for old_name in old_names:
    new_name = CLASS_MAP.get(old_name, old_name)

    if new_name is not None and new_name not in new_names:
        new_names.append(new_name)

print("\n새 클래스:")
for i, name in enumerate(new_names):
    print(i, name)


# 기존 class id → 새로운 class id
id_map = {}

for old_id, old_name in enumerate(old_names):

    new_name = CLASS_MAP.get(old_name, old_name)

    if new_name is None:
        id_map[old_id] = None
    else:
        id_map[old_id] = new_names.index(new_name)


# 라벨 백업
backup_dir = Path("labels_backup")

if not backup_dir.exists():

    for split in ["train", "valid", "test"]:

        label_dir = DATASET_DIR / split / "labels"

        if label_dir.exists():
            shutil.copytree(
                label_dir,
                backup_dir / split / "labels"
            )

    shutil.copy(
        YAML_PATH,
        backup_dir / "data.yaml"
    )

    print("\n라벨 백업 완료:", backup_dir)


# 라벨 변경
for split in ["train", "valid", "test"]:

    label_dir = DATASET_DIR / split / "labels"

    if not label_dir.exists():
        continue

    files = list(label_dir.glob("*.txt"))

    print(f"\n{split}: {len(files)}개 처리 중")

    for txt_file in files:

        new_lines = []

        with open(txt_file, "r", encoding="utf-8") as f:

            for line in f:

                parts = line.strip().split()

                if not parts:
                    continue

                old_class_id = int(float(parts[0]))

                new_class_id = id_map.get(old_class_id)

                # 삭제할 클래스
                if new_class_id is None:
                    continue

                parts[0] = str(new_class_id)

                new_lines.append(" ".join(parts))

        with open(txt_file, "w", encoding="utf-8") as f:

            if new_lines:
                f.write("\n".join(new_lines) + "\n")


# data.yaml 수정
data["names"] = new_names
data["nc"] = len(new_names)

with open(YAML_PATH, "w", encoding="utf-8") as f:
    yaml.safe_dump(
        data,
        f,
        allow_unicode=True,
        sort_keys=False
    )

print("\n클래스 정리 완료!")
print("클래스 수:", len(new_names))
print("classes:", new_names)