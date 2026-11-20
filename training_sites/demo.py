"""Reproducible synthetic fixtures for checking the two local workspaces."""

from math import sin


def score_file():
    from music21 import key, meter, note, stream, tempo
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    score = stream.Score()
    hands = (stream.Part(), stream.Part())
    for part, name in zip(hands, ("Upper", "Lower")):
        part.partName = name
        score.insert(0, part)
    melody = ("C5 E5 G5 A5", "G5 E5 D5 G5", "E5 G5 A5 C6", "B5 A5 G5 D5",
              "E5 F5 G5 E5", "C5 E5 A5 G5", "F5 D5 G5 B5", "C6 G5 E5 C5")
    bass = ("C3 G3", "G2 D3", "A2 E3", "G2 D3", "F2 C3", "A2 E3", "G2 D3", "C3 G3")
    for position, (upper, lower) in enumerate(zip(melody, bass), 1):
        for part, pitches, duration in zip(hands, (upper, lower), (1, 2)):
            measure = stream.Measure(number=position)
            if position == 1:
                measure.insert(0, meter.TimeSignature("4/4"))
                measure.insert(0, key.Key("C"))
            if part is hands[0] and position in {1, 5}:
                measure.insert(0, tempo.MetronomeMark(number=96 if position == 1 else 112))
            for pitch in pitches.split():
                measure.append(note.Note(pitch, quarterLength=duration))
            part.append(measure)
    return GeneralObjectExporter(score).parse()


def alignment_dataset():
    examples = []
    for piece in range(8):
        scale = (0, 2, 4, 5, 7, 9, 11)
        root = 59 + piece
        for take in range(2):
            reference, performance, matches = [], [], []
            for beat in range(20):
                onset = round(beat * (0.43 + piece * 0.012), 4)
                center = root + scale[(beat * (3 + piece % 2) + beat // 3 + take) % 7]
                pitches = sorted({center, center - (5 + beat % 4), center - 12})
                if beat % 4 == 1:
                    pitches = [center]
                for voice, pitch in enumerate(pitches):
                    ref_id, perf_id = f"r{beat}-{voice}", f"p{beat}-{voice}"
                    reference.append({"id": ref_id, "pitch": pitch, "onset": onset, "duration": 0.28})
                    if (beat + piece + take) % 11 == 3 and voice == 0:
                        continue
                    bend = (0.38 + take * .04) * abs(onset - (4 + piece * .035))
                    timing = 0.64 + onset + bend + .13 * sin(beat * .87 + piece)
                    timing += voice * (.028 + .011 * (take == 1))
                    performance.append({"id": perf_id, "pitch": pitch, "onset": round(timing, 4),
                                        "duration": round(.23 + .04 * sin(beat), 4)})
                    matches.append({"reference_id": ref_id, "performance_id": perf_id})
                if beat in {6, 14}:
                    performance.append({"id": f"extra-{beat}", "pitch": center + 13,
                                        "onset": round(timing + .07, 4), "duration": .16})
            examples.append({"id": f"示例 {piece + 1} · 第 {take + 1} 遍", "piece_id": f"demo-{piece + 1}",
                             "reference": reference, "performance": performance, "matches": matches})
    return {"version": 1, "synthetic": True, "examples": examples}
