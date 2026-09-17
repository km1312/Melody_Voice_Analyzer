"""Train the stance head in revolv/assets/stance_head.npz from scratch.

    .venv\\Scripts\\python.exe tools\\train_stance_head.py

Downloads SpeechSense (CC-BY-4.0: BruceW13/SpeechSense-Training for training,
BruceW13/SpeechSense for the held-out test), encodes every clip with the same
Whisper large-v3 CTranslate2 model the pipeline loads, and fits a standardised
multinomial logistic regression on mean+std pooled last-layer states. The
regularisation strength is chosen by stratified cross-validation on the training
set alone; the test set is touched once, at the end.

Writes the head, and a JSON report beside it with every number quoted about it.
"""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from revolv import stance  # noqa: E402
from revolv.audio import load_audio  # noqa: E402

TRAIN_REPO = "BruceW13/SpeechSense-Training"
TEST_REPO = "BruceW13/SpeechSense"
C_GRID = (0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0)


def _token():
    try:
        from revolv.config import Settings

        return Settings().get("hf_token") or None
    except Exception:
        return None


def _download(repo):
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo, repo_type="dataset", max_workers=2, token=_token()))


def _read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _items(root, label_file, audio_dir):
    rows = _read_jsonl(root / label_file)
    items = []
    for row in rows:
        relative = row.get("audio_path") or row.get("audio_name") or row.get("path")
        path = root / audio_dir / relative
        if not path.exists():
            path = root / audio_dir / Path(relative).name
        label = row.get("label_name") or row.get("label")
        items.append((path, str(label).lower()))
    return items


def _features(model, items, cache):
    if cache.exists():
        data = np.load(cache, allow_pickle=False)
        if len(data["x"]) == len(items):
            return data["x"], [str(y) for y in data["y"]]
    xs, ys, clips, labels = [], [], [], []
    began = time.time()

    def flush():
        states = stance.encoder_states_batch(model, clips, 16000)
        xs.extend(stance.pooled(s) for s in states)
        ys.extend(labels)
        clips.clear()
        labels.clear()

    for index, (path, label) in enumerate(items):
        clips.append(load_audio(str(path), target_sr=16000))
        labels.append(label)
        if len(clips) == stance.ENCODER_BATCH:
            flush()
        if (index + 1) % 200 == 0:
            print("  encoded {0}/{1} in {2:.0f}s".format(index + 1, len(items),
                                                          time.time() - began), flush=True)
    if clips:
        flush()
    x = np.stack(xs)
    np.savez_compressed(cache, x=x, y=np.array(ys))
    return x, ys


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(stance.HEAD_PATH))
    parser.add_argument("--cache", default=str(ROOT / "build" / "stance_features"))
    args = parser.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    print("downloading SpeechSense", flush=True)
    train_root = _download(TRAIN_REPO)
    test_root = _download(TEST_REPO)
    train_items = _items(train_root, "training_set_label_audio.jsonl", "training_set")
    test_items = _items(test_root, "test_set_label.jsonl", "test_set")
    print("  {0} training clips, {1} test clips".format(len(train_items), len(test_items)))

    print("loading Whisper large-v3 (the pipeline's own model)", flush=True)
    import whisperx

    model = whisperx.load_model("large-v3", device="cuda", compute_type="float16",
                                language="en").model

    print("encoding training clips", flush=True)
    x_train, y_train = _features(model, train_items, cache / "train.npz")
    print("encoding test clips", flush=True)
    x_test, y_test = _features(model, test_items, cache / "test.npz")

    labels = [label for label in stance.STANCE_LABELS if label in set(y_train)]
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    scores = {}
    for c in C_GRID:
        estimator = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000))
        predicted = cross_val_predict(estimator, x_train, y_train, cv=folds)
        scores[c] = f1_score(y_train, predicted, average="macro")
        print("  C={0:<7} cross-validated macro-F1 {1:.3f}".format(c, scores[c]), flush=True)
    best = max(scores, key=scores.get)

    estimator = make_pipeline(StandardScaler(), LogisticRegression(C=best, max_iter=5000))
    estimator.fit(x_train, y_train)
    predicted = estimator.predict(x_test)
    scaler, classifier = estimator.named_steps.values()
    order = [list(classifier.classes_).index(label) for label in labels]

    report = {
        "trained": datetime.date.today().isoformat(),
        "data": {"train": TRAIN_REPO, "test": TEST_REPO, "licence": "CC-BY-4.0",
                 "train_clips": len(y_train), "test_clips": len(y_test)},
        "encoder": "openai whisper large-v3, faster-whisper CTranslate2 float16, "
                   "last encoder layer, mean+std over frames",
        "classifier": "StandardScaler + multinomial LogisticRegression",
        "C": best,
        "cv_macro_f1_by_C": {str(k): round(v, 4) for k, v in scores.items()},
        "test_accuracy": round(accuracy_score(y_test, predicted), 4),
        "test_macro_f1": round(f1_score(y_test, predicted, average="macro"), 4),
        "test_per_class": classification_report(y_test, predicted, labels=labels,
                                                output_dict=True, zero_division=0),
        "test_confusion": {"labels": labels,
                           "matrix": confusion_matrix(y_test, predicted, labels=labels).tolist()},
    }
    print("test accuracy {0}, macro-F1 {1}".format(report["test_accuracy"],
                                                    report["test_macro_f1"]), flush=True)

    # Two numbers that say what the cross-validation figure does not. The
    # training texts were written to express each stance, so a classifier that
    # reads only the *words* separates them almost as well as one that hears the
    # audio: that is why cross-validated F1 on the training set says ~0.95 while
    # the held-out test says ~0.4. And the axis the analysis uses is
    # P(confident) - P(nervous), so its test AUC is reported on its own.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import roc_auc_score

    text_rows = _read_jsonl(train_root / "training_set_label_text.jsonl")
    text_pred = cross_val_predict(
        make_pipeline(TfidfVectorizer(ngram_range=(1, 2)),
                      LogisticRegression(C=10, max_iter=5000)),
        [r["text"] for r in text_rows], [r["label_name"] for r in text_rows], cv=folds)
    report["train_text_only_cv_macro_f1"] = round(
        f1_score([r["label_name"] for r in text_rows], text_pred, average="macro"), 4)
    probabilities = estimator.predict_proba(x_test)
    classes = list(classifier.classes_)
    axis = probabilities[:, classes.index("confident")] - probabilities[:, classes.index("nervous")]
    pair = np.array([label in ("confident", "nervous") for label in y_test])
    report["test_certainty_auc_confident_vs_nervous"] = round(float(roc_auc_score(
        np.array([label == "confident" for label in y_test])[pair], axis[pair])), 4)
    report["test_certainty_mean_by_label"] = {
        label: round(float(axis[np.array([v == label for v in y_test])].mean()), 4)
        for label in labels}
    print("text-only CV macro-F1 {0}; certainty AUC {1}".format(
        report["train_text_only_cv_macro_f1"],
        report["test_certainty_auc_confident_vs_nervous"]), flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    info = {k: report[k] for k in ("trained", "data", "encoder", "classifier", "C",
                                   "test_accuracy", "test_macro_f1",
                                   "train_text_only_cv_macro_f1",
                                   "test_certainty_auc_confident_vs_nervous")}
    np.savez(out,
             mean=scaler.mean_.astype(np.float32),
             scale=scaler.scale_.astype(np.float32),
             coef=classifier.coef_[order].astype(np.float32),
             intercept=classifier.intercept_[order].astype(np.float32),
             labels=np.array(labels),
             info=np.array(json.dumps(info)))
    with open(out.with_suffix(".json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
