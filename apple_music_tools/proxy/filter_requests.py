from datetime import datetime

import typer
from mitmproxy.http import HTTPFlow
from relational_stream import Flow, RelationalStream

from apple_music_tools.proxy.models import (
    AppleMusicDownload,
    AppleMusicKey,
    PlaybackDispatchFormatException,
)

PLAYBACK_DISPATCH_URL = "https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/subPlaybackDispatch"
FPS_URL = "https://play.itunes.apple.com/WebObjects/MZPlay.woa/music/fps"


class AppleMusicKeyCollectorAddon:
    keys: dict[str, AppleMusicKey] = {}

    def response(self, flow: HTTPFlow):
        if flow.request.url != FPS_URL or flow.response is None or flow.response.status_code != 200:
            return

        assert flow.response.text is not None

        uri = flow.request.json()["keyUri"]
        ckc = flow.response.json()["ckc"]
        issued = datetime.fromtimestamp(flow.client_conn.timestamp_start)
        expiration = datetime.fromtimestamp(
            datetime.timestamp(issued) + flow.response.json()["renew-after"]
        )
        self.keys[uri] = AppleMusicKey(uri=uri, ckc=ckc, issued=issued, expiration=expiration)


class AppleMusicDownloadAddon(RelationalStream):
    def __init__(self) -> None:
        super().__init__([AppleMusicDownloadFlow])

    def response(self, flow: HTTPFlow):
        self.ingest(flow)


class AppleMusicDownloadFlow(Flow[HTTPFlow]):
    download: AppleMusicDownload

    def __init__(self, events: list[HTTPFlow]):
        super().__init__(events)
        self.download = AppleMusicDownload()

    def is_next_event(self, event: HTTPFlow) -> bool:
        if self.download.playback_dispatch is None:
            if event.request.url == PLAYBACK_DISPATCH_URL:
                return self.handle_playback_dispatch(event)
            else:  # require first event to be a playback dispatch
                return False

        elif event.request.url == self.download.hls_playlist_url:
            return self.handle_hls_playlist(event)
        elif (
            self.download.hls_playlist is not None
            and event.request.url in self.download.hls_stream_variants
        ):
            return self.handle_hls_stream_info(event)
        return False

    def is_complete(self) -> bool:
        return self.download.selected_hls_stream_info is not None

    def handle_playback_dispatch(self, flow: HTTPFlow) -> bool:
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping playback dispatch with status code {flow.response.status_code}!")
            return False
        assert flow.response.text is not None

        try:
            AppleMusicDownload.validate_playback_dispatch(flow.response.text)
        except PlaybackDispatchFormatException:
            print("Skipping playback dispatch with bad format!")
            return False

        self.download = AppleMusicDownload(playback_dispatch=flow.response.text)
        return True

    def handle_hls_playlist(self, flow: HTTPFlow) -> bool:
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping hls playlist with status code {flow.response.status_code}!")
            return False
        assert flow.response.text is not None

        self.download.hls_playlist = flow.response.text
        return True

    def handle_hls_stream_info(self, flow: HTTPFlow) -> bool:
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping hls stream info with status code {flow.response.status_code}!")
            return False
        assert flow.response.text is not None

        self.download.selected_hls_stream_info_url = flow.request.url
        self.download.selected_hls_stream_info = flow.response.text
        return True


apple_music_download_addon = AppleMusicDownloadAddon()
apple_music_key_collector_addon = AppleMusicKeyCollectorAddon()
addons = [apple_music_download_addon, apple_music_key_collector_addon]


def __dedup_downloads(downloads: list[AppleMusicDownload]):
    dedup_downloads = []
    download_streams = set()
    for d in downloads:
        if d.selected_hls_stream_info_url not in download_streams:
            dedup_downloads.append(d)
            download_streams.add(d.selected_hls_stream_info_url)
    return dedup_downloads


def get_completed() -> list[AppleMusicDownload]:
    downloads = __dedup_downloads(
        [f.download for f in apple_music_download_addon.completed_flows(AppleMusicDownloadFlow)]
    )
    keys = apple_music_key_collector_addon.keys

    for d in downloads:
        d.keys = keys

    return downloads
