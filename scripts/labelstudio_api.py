"""Minimal Label Studio client using session login (legacy API tokens are disabled by default).

Usage:
  python scripts/labelstudio_api.py create-project
  python scripts/labelstudio_api.py import labeling/tasks/batch1.json
  python scripts/labelstudio_api.py export  > data/gold/batch1.export.json
"""

from __future__ import annotations

import http.cookiejar
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8080"
USER = "annotator@local.test"
PASSWORD = "caselaw-local-2026"
PROJECT_ID_FILE = pathlib.Path("labeling/data/project_id")


class Client:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._login()

    def _csrf(self) -> str:
        for c in self.jar:
            if c.name == "csrftoken":
                return c.value
        raise RuntimeError("no csrftoken cookie")

    def _login(self) -> None:
        page = self.opener.open(f"{BASE}/user/login/").read().decode()
        m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
        token = m.group(1) if m else self._csrf()
        data = urllib.parse.urlencode(
            {"email": USER, "password": PASSWORD, "csrfmiddlewaretoken": token}
        ).encode()
        req = urllib.request.Request(
            f"{BASE}/user/login/", data=data, headers={"Referer": f"{BASE}/user/login/"}
        )
        self.opener.open(req)
        if not any(c.name == "sessionid" for c in self.jar):
            raise RuntimeError("login failed: no sessionid cookie")

    def call(self, method: str, path: str, body: object | None = None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": self._csrf(),
                "Referer": BASE,
            },
        )
        with self.opener.open(req) as r:
            raw = r.read()
        return json.loads(raw) if raw else None


def main(argv: list[str]) -> None:
    c = Client()
    cmd = argv[1]
    if cmd == "whoami":
        print(c.call("GET", "/api/current-user/whoami"))
    elif cmd == "create-project":
        cfg = pathlib.Path("labeling/label_config.xml").read_text()
        d = c.call(
            "POST",
            "/api/projects",
            {
                "title": "BGer civil law - gold set",
                "description": "German civil-law BGer decisions 2020-2026, regex pre-annotated",
                "label_config": cfg,
                "show_collab_predictions": True,
            },
        )
        assert isinstance(d, dict)
        PROJECT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROJECT_ID_FILE.write_text(str(d["id"]))
        print("project", d["id"], d["title"])
    elif cmd == "import":
        pid = PROJECT_ID_FILE.read_text().strip()
        tasks = json.loads(pathlib.Path(argv[2]).read_text())
        d = c.call("POST", f"/api/projects/{pid}/import?return_task_ids=true", tasks)
        assert isinstance(d, dict)
        print({k: d.get(k) for k in ("task_count", "annotation_count", "prediction_count")})
    elif cmd == "export":
        pid = PROJECT_ID_FILE.read_text().strip()
        d = c.call("GET", f"/api/projects/{pid}/export?exportType=JSON&download_all_tasks=false")
        print(json.dumps(d, ensure_ascii=False))
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main(sys.argv)
