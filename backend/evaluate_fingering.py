"""Prepare blind note labels and calculate metrics for manually labeled videos."""

import argparse
import csv
import json
from pathlib import Path


LABEL_COLUMNS = ("job_id", "note_index", "note_name", "video_seconds", "frame", "hand", "finger", "scenario")


def read_job(path):
    summary = json.loads((path / "analysis_summary.json").read_text(encoding="utf-8"))
    with (path / "fingering_predictions.csv").open(encoding="utf-8-sig", newline="") as stream:
        predictions = {row["note_index"]: row for row in csv.DictReader(stream)}
    return summary, predictions


def make_labels(jobs, destination):
    with destination.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        for job in jobs:
            summary, predictions = read_job(job)
            for index, row in predictions.items():
                time = float(row["start_seconds"]) + summary["offset_seconds"]
                if 0 <= time < summary["video_duration_seconds"]:
                    writer.writerow(dict(job_id=job.name, note_index=index, note_name=row["note_name"],
                                         video_seconds=round(time, 4), frame=row["start_frame"]))


def ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def calculate(samples):
    labels = len(samples)
    hand_labels = sum(row["hand"] in ("left", "right") for row, _, _ in samples)
    finger_labels = sum(bool(row["finger"]) for row, _, _ in samples)
    matched = sum(pred["status"] == "matched" for _, pred, _ in samples)
    matched_hands = sum(row["hand"] in ("left", "right") and pred["status"] == "matched" for row, pred, _ in samples)
    matched_fingers = sum(bool(row["finger"]) and pred["status"] == "matched" for row, pred, _ in samples)
    hand_correct = sum(row["hand"] in ("left", "right") and row["hand"] == pred["hand"] for row, pred, _ in samples)
    finger_correct = sum(
        bool(row["finger"]) and (row["hand"], row["finger"]) == (pred["hand"], pred["finger"])
        for row, pred, _ in samples
    )
    hand_detected = sum(detected for _, _, detected in samples)
    label_predictability = {
        "手别有标签": hand_labels, "手别与指号均有标签": finger_labels,
        "手别有标签且系统给候选": matched_hands, "指法有标签且系统给候选": matched_fingers,
    }
    return {
        "已检查音符": labels,
        **label_predictability,
        "有手部检出比例": ratio(hand_detected, labels),
        "几何候选覆盖率": ratio(matched, labels),
        "拒识比例": ratio(labels - matched, labels),
        "左右手准确率_可判定且有候选": ratio(hand_correct, matched_hands),
        "指法准确率_可判定且有候选": ratio(finger_correct, matched_fingers),
        "左右手准确率_全部手别有标签样本": ratio(hand_correct, hand_labels),
        "指法准确率_全部指法有标签样本": ratio(finger_correct, finger_labels),
        "左右手确认正确比例_全部检查样本": ratio(hand_correct, labels),
        "指法确认正确比例_全部检查样本": ratio(finger_correct, labels),
    }


def evaluate(jobs, labels):
    sources = {}
    for job in jobs:
        _, predictions = read_job(job)
        with (job / "aligned_landmarks.jsonl").open(encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream]
        sources[job.name] = (predictions, {str(row["note_index"]) for row in rows if row["hands"]})

    samples = []
    seen = set()
    unreviewed = 0
    with labels.open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), start=2):
            job_id, note_id = row["job_id"], row["note_index"]
            if job_id not in sources or note_id not in sources[job_id][0] or (job_id, note_id) in seen:
                raise ValueError(f"第 {line} 行任务/音符不存在或重复")
            seen.add((job_id, note_id))
            hand, finger = row["hand"].strip().lower(), row["finger"].strip()
            if not hand and not finger:
                unreviewed += 1
                continue
            if hand not in ("left", "right", "unknown") or (finger and (hand == "unknown" or finger not in "12345" or len(finger) != 1)):
                raise ValueError(f"第 {line} 行手别或指号格式不正确")
            predictions, detections = sources[job_id]
            samples.append(({**row, "hand": hand, "finger": finger}, predictions[note_id], note_id in detections))
    if not samples:
        raise ValueError("请至少检查并填写一个音符，无法判断的手别写 unknown")
    scenarios = sorted({row["scenario"].strip() for row, _, _ in samples} - {""})
    return {
        "总计": calculate(samples), "未检查音符": unreviewed,
        "按场景": {key: calculate([sample for sample in samples if sample[0]["scenario"].strip() == key])
                 for key in scenarios},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("template", "evaluate"))
    parser.add_argument("--jobs", required=True, nargs="+", type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if len({job.name for job in args.jobs}) != len(args.jobs):
        parser.error("请指定名称不同的任务目录")
    try:
        if args.command == "template":
            make_labels(args.jobs, args.labels)
            print(f"已生成空白标注表 {args.labels}")
        else:
            result = json.dumps(evaluate(args.jobs, args.labels), indent=2, ensure_ascii=False)
            if args.output:
                args.output.write_text(result + "\n", encoding="utf-8")
            print(result)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
