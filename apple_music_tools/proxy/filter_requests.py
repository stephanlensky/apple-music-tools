import itertools

import typer
from mitmproxy.http import HTTPFlow

from apple_music_tools.proxy.models import PlaybackDispatchFormatException, SongDownloadFlow

PLAYBACK_DISPATCH_URL = "https://play.itunes.apple.com/WebObjects/MZPlay.woa/wa/subPlaybackDispatch"
FPS_URL = "https://play.itunes.apple.com/WebObjects/MZPlay.woa/music/fps"


class SongDownloadFlowCollector:
    __id_counter: itertools.count
    in_progress_sd_flows: dict[int, SongDownloadFlow]  # id -> SongDownloadFlow
    hls_playlist_urls: dict[str, int]  # expected hls playlist url -> flow id
    hls_stream_variants: dict[str, int]  # stream variant url -> flow id
    required_key_uris: dict[str, set[int]]  # key uri -> set[flow id]
    completed_sd_flows: list[SongDownloadFlow]
    extra_keys: dict[
        str, str
    ]  # sometimes keys may be fetched before a download begins but needed later

    def __init__(self):
        self.__id_counter = itertools.count()
        self.in_progress_sd_flows = {}
        self.hls_playlist_urls = {}
        self.hls_stream_variants = {}
        self.required_key_uris = {}
        self.completed_sd_flows = []
        self.extra_keys = {}

    def response(self, flow: HTTPFlow):
        if flow.request.url == PLAYBACK_DISPATCH_URL:
            typer.echo("Playback dispatch")
            self.handle_playback_dispatch(flow)
        elif flow.request.url in self.hls_playlist_urls:
            typer.echo("HLS playlist fetch")
            self.handle_hls_playlist(flow)
        elif flow.request.url in self.hls_stream_variants:
            typer.echo("HLS stream info fetch")
            self.handle_hls_stream_info(flow)
        elif flow.request.url == FPS_URL:
            typer.echo("Key fetch")
            self.handle_key_request(flow)

    def handle_playback_dispatch(self, flow: HTTPFlow):
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping playback dispatch with status code {flow.response.status_code}!")
            return
        assert flow.response.text is not None

        try:
            SongDownloadFlow.validate_playback_dispatch(flow.response.text)
        except PlaybackDispatchFormatException:
            print("Skipping playback dispatch with bad format!")
            return

        sd_flow = SongDownloadFlow(id=next(self.__id_counter), playback_dispatch=flow.response.text)
        self.in_progress_sd_flows[sd_flow.id] = sd_flow
        self.hls_playlist_urls[sd_flow.hls_playlist_url] = sd_flow.id

    def handle_hls_playlist(self, flow: HTTPFlow):
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping hls playlist with status code {flow.response.status_code}!")
            return
        assert flow.response.text is not None

        flow_id = self.hls_playlist_urls.pop(flow.request.url)
        sd_flow = self.in_progress_sd_flows[flow_id]
        sd_flow.hls_playlist = flow.response.text
        self.hls_stream_variants.update({sv: flow_id for sv in sd_flow.hls_stream_variants})

    def handle_hls_stream_info(self, flow: HTTPFlow):
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping hls stream info with status code {flow.response.status_code}!")
            return
        assert flow.response.text is not None

        flow_id = self.hls_stream_variants.pop(flow.request.url)
        # discard unused stream variants
        for url, id_ in list(self.hls_stream_variants.items()):
            if id_ == flow_id:
                del self.hls_stream_variants[url]

        sd_flow = self.in_progress_sd_flows[flow_id]
        sd_flow.selected_hls_stream_info = flow.response.text

        for key_uri in sd_flow.required_key_uris:
            if key_uri in self.extra_keys:
                print(f"Using extra key {key_uri}")
                sd_flow.keys[key_uri] = self.extra_keys[key_uri]
                if not sd_flow.missing_key_uris():
                    self.mark_complete(flow_id)
                continue

            if key_uri not in self.required_key_uris:
                self.required_key_uris[key_uri] = set()
            self.required_key_uris[key_uri].add(flow_id)

    def handle_key_request(self, flow: HTTPFlow):
        assert flow.response is not None
        if flow.response.status_code != 200:
            typer.echo(f"Skipping hls playlist with status code {flow.response.status_code}!")
            return
        assert flow.response.text is not None

        key_uri = flow.request.json()["keyUri"]
        key = flow.response.json()["ckc"]

        if key_uri not in self.required_key_uris:
            print(f"Storing unneeded key {key_uri}...")
            self.extra_keys[key_uri] = key
            return

        for flow_id in self.required_key_uris[key_uri]:
            sd_flow = self.in_progress_sd_flows[flow_id]
            sd_flow.keys[key_uri] = key

            if not sd_flow.missing_key_uris():
                self.mark_complete(flow_id)

        del self.required_key_uris[key_uri]

    def mark_complete(self, flow_id):
        print("Completed flow!")
        sd_flow = self.in_progress_sd_flows[flow_id]
        del self.in_progress_sd_flows[flow_id]
        self.completed_sd_flows.append(sd_flow)

    def finalize(self):
        print(f"In progress: {[sd.song_title for sd in self.in_progress_sd_flows.values()]}")
        print(f"Completed: {[sd.song_title for sd in self.completed_sd_flows]}")


addons = [SongDownloadFlowCollector()]
