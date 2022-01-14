import subprocess
from pathlib import Path

import typer
from mitmproxy import http, io
from mitmproxy.exceptions import FlowReadException

from apple_music_tools.proxy import filter_requests

app = typer.Typer()

addon_modules = [filter_requests]


@app.command()
def start():
    opts = sum([["-s", a.__file__] for a in addon_modules], [])
    subprocess.run(["mitmdump"] + opts, check=False)


@app.command()
def parse_capture(
    capture: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True)
):
    flows_with_responses: list[http.HTTPFlow] = []
    with open(capture, "rb") as logfile:
        freader = io.FlowReader(logfile)
        try:
            for f in freader.stream():
                if isinstance(f, http.HTTPFlow) and f.response is not None:
                    flows_with_responses.append(f)
        except FlowReadException as e:
            print(f"Flow file corrupted: {e}")

    for f in flows_with_responses:
        for m in addon_modules:
            for addon in m.addons:  # type: ignore
                addon.response(f)

    for m in addon_modules:
        for addon in m.addons:  # type: ignore
            addon.finalize()
