"""MLflow tracking for extractor runs. Local SQLite store so the model registry works."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

TRACKING_URI = "sqlite:///mlflow.db"
EXPERIMENT = "caselaw-extraction"


def _mlflow():
    import mlflow

    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT)
    return mlflow


@contextmanager
def run(name: str, params: dict[str, Any] | None = None, tags: dict[str, str] | None = None):
    mlflow = _mlflow()
    with mlflow.start_run(run_name=name, tags=tags) as r:
        if params:
            mlflow.log_params({k: str(v)[:500] for k, v in params.items()})
        yield Logger(mlflow, r.info.run_id)


class Logger:
    def __init__(self, mlflow, run_id: str) -> None:
        self.mlflow = mlflow
        self.run_id = run_id

    def metrics(self, m: dict[str, float], step: int | None = None) -> None:
        self.mlflow.log_metrics({k: float(v) for k, v in m.items()}, step=step)

    def artifact(self, path: Path | str) -> None:
        self.mlflow.log_artifact(str(path))

    def text(self, text: str, name: str) -> None:
        self.mlflow.log_text(text, name)
