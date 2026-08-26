#!/usr/bin/env python3
"""Serve the APPA web UI with byte-range support for audio seeking."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Static file handler that supports HTTP Range requests.

    Browser media elements need `206 Partial Content` responses to seek inside
    long MP3 previews without downloading the whole file from the start.
    """

    range: tuple[int, int] | None = None
    project_root = PROJECT_ROOT

    def python_executable(self) -> str:
        venv_python = self.project_root / ".venv" / "bin" / "python"
        return str(venv_python) if venv_python.exists() else sys.executable

    def do_POST(self):
        clean_path = self.path.split("?", 1)[0]
        if clean_path == "/api/session/prepare":
            self.handle_prepare_session()
            return
        if clean_path == "/api/bss/analyze":
            self.handle_bss_analyze()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        return json.loads(body.decode("utf-8"))

    def send_json_response(self, payload: str | dict, status: HTTPStatus = HTTPStatus.OK):
        if isinstance(payload, str):
            response = payload.encode("utf-8")
        else:
            response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def run_json_command(self, command: list[str]) -> str:
        try:
            result = subprocess.run(
                command,
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise RuntimeError(detail) from error
        return result.stdout

    def handle_prepare_session(self):
        try:
            payload = self.read_json_body()
            file_names = payload.get("fileNames") or []
            command = [
                self.python_executable(),
                str(self.project_root / "scripts" / "prepare_session_assets.py"),
            ]
            for file_name in file_names:
                command.extend(["--file-name", str(file_name)])

            self.send_json_response(self.run_json_command(command))
        except Exception as error:
            self.send_json_response({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_bss_analyze(self):
        try:
            payload = self.read_json_body()
            session_id = str(payload.get("sessionId") or "miuse-full")
            start = float(payload.get("start") or 0)
            duration = float(payload.get("duration") or 360)
            algorithms = payload.get("algorithms") or ["auxiva"]
            if not isinstance(algorithms, list):
                algorithms = ["auxiva"]

            command = [
                self.python_executable(),
                str(self.project_root / "scripts" / "run_bss_cache.py"),
                "--session-id",
                session_id,
                "--start",
                str(start),
                "--duration",
                str(duration),
                "--algorithms",
                *[str(algorithm) for algorithm in algorithms],
            ]

            self.send_json_response(self.run_json_command(command))
        except Exception as error:
            self.send_json_response({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = self.path.split("?")
            clean_path = parts[0]
            if not clean_path.endswith("/"):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", clean_path + "/" + ("?" + parts[1] if len(parts) > 1 else ""))
                self.end_headers()
                return None
            for index in ("index.html", "index.htm"):
                index_path = os.path.join(path, index)
                if os.path.isfile(index_path):
                    path = index_path
                    break
            else:
                return self.list_directory(path)

        ctype = self.guess_type(path)
        try:
            file = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        size = os.fstat(file.fileno()).st_size
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")

        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                file.close()
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return None

            first, last = match.groups()
            if first == "" and last == "":
                file.close()
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return None

            if first == "":
                length = int(last)
                start = max(size - length, 0)
            else:
                start = int(first)
                if last:
                    end = min(int(last), size - 1)

            if start >= size or start > end:
                file.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None

            status = HTTPStatus.PARTIAL_CONTENT

        self.range = (start, end)
        self.send_response(status)
        self.send_header("Content-type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", self.date_time_string(os.fstat(file.fileno()).st_mtime))
        self.end_headers()
        return file

    def copyfile(self, source, outputfile):
        if not self.range:
            return super().copyfile(source, outputfile)

        start, end = self.range
        source.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            try:
                outputfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break
            remaining -= len(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve APPA web assets with HTTP range support.")
    parser.add_argument("--port", type=int, default=5177)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--directory", default=None)
    args = parser.parse_args()

    directory = Path(args.directory).expanduser() if args.directory else PROJECT_ROOT / "web"
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    directory = directory.resolve()
    if not directory.is_dir():
        parser.error(f"Web directory does not exist: {directory}")

    handler = partial(RangeRequestHandler, directory=directory)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {directory} at http://{args.host}:{args.port}/ with byte-range support", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAPPA web server stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
