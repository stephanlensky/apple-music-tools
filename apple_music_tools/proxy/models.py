import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse, urlunparse

import m3u8
from pydantic import BaseModel, validator

from apple_music_tools.proxy.plist_xml_util import get_xml_array_index, get_xml_dict_key


class PlaybackDispatchFormatException(Exception):
    """
    Thrown when the playback dispatch XML is not in the expected format.

    Apple Music can hit the playback dispatch endpoint for multiple reasons, but we are only
    interested in one of them (song downloads).
    """


class AppleMusicKey(BaseModel):
    uri: str
    issued: datetime
    expiration: datetime
    ckc: str


class AppleMusicDownload(BaseModel):
    playback_dispatch: Optional[str]
    hls_playlist: Optional[str]
    selected_hls_stream_info_url: Optional[str]
    selected_hls_stream_info: Optional[str]
    keys: dict[str, AppleMusicKey] = {}  # keyUri -> key

    @validator("playback_dispatch")
    @classmethod
    def validate_playback_dispatch(cls, v):
        # if this throws an exception, the playback dispatch is not valid
        cls.__get_hls_playlist_url_from_playback_dispatch(v)
        return v

    @property
    def hls_playlist_url(self) -> str:
        """Parse the HLS playlist URL from the playback dispatch XML."""
        assert self.playback_dispatch is not None
        return self.__get_hls_playlist_url_from_playback_dispatch(self.playback_dispatch)

    @staticmethod
    def __get_hls_playlist_url_from_playback_dispatch(playback_dispatch: str):
        root = ET.fromstring(playback_dispatch)
        main_dict = root.find("dict")
        assert main_dict is not None
        try:
            song_list = get_xml_dict_key(main_dict, "songList")
            song_dict = get_xml_array_index(song_list, 0)
            playlist_url = get_xml_dict_key(song_dict, "hls-playlist-url").text
        except (KeyError, IndexError) as e:
            raise PlaybackDispatchFormatException from e
        return playlist_url

    @property
    def hls_stream_variants(self) -> set[str]:
        assert self.hls_playlist is not None
        playlist = m3u8.loads(self.hls_playlist)
        assert playlist.is_variant

        hls_playlist_url = urlparse(self.hls_playlist_url)
        base_path = PurePosixPath(hls_playlist_url.path).parent

        return {
            urlunparse(hls_playlist_url._replace(path=str(base_path / p.uri)))
            for p in playlist.playlists
        }

    @property
    def required_key_uris(self) -> set[str]:
        assert self.selected_hls_stream_info is not None
        playlist = m3u8.loads(self.selected_hls_stream_info)
        return {k.uri for k in playlist.keys}

    @property
    def song_title(self) -> str:
        assert self.playback_dispatch is not None
        root = ET.fromstring(self.playback_dispatch)
        main_dict = root.find("dict")
        assert main_dict is not None
        try:
            song_list = get_xml_dict_key(main_dict, "songList")
            song_dict = get_xml_array_index(song_list, 0)
            assets_array = get_xml_dict_key(song_dict, "assets")
            song_assets_dict = get_xml_array_index(assets_array, 0)
            song_metadata_dict = get_xml_dict_key(song_assets_dict, "metadata")
            song_title = get_xml_dict_key(song_metadata_dict, "itemName").text
        except (KeyError, IndexError) as e:
            raise PlaybackDispatchFormatException from e
        return song_title

    def missing_key_uris(self) -> set[str]:
        required_key_uris = self.required_key_uris
        for key_uri in self.keys:
            if key_uri in required_key_uris:
                required_key_uris.remove(key_uri)
        return required_key_uris

    def __str__(self) -> str:
        title = self.song_title if self.playback_dispatch else "(Unknown)"
        playback_dispatch_status = "Present" if self.playback_dispatch else "None"
        hls_playlist_url = self.hls_playlist_url if self.playback_dispatch else "None"
        hls_playlist_status = "Present" if self.hls_playlist else "None"
        stream_info_status = (
            f"Present ({self.selected_hls_stream_info_url})"
            if self.selected_hls_stream_info
            else "None"
        )
        required_keys = "Unknown" if not self.selected_hls_stream_info else self.required_key_uris
        missing_keys = (
            "Unknown"
            if not self.selected_hls_stream_info
            else (self.missing_key_uris() if self.missing_key_uris() else "")
        )
        return (
            f"{title}:\n\tPlayback dispatch: {playback_dispatch_status}\n\tHLS playlist URL:"
            f" {hls_playlist_url}\n\tHLS playlist: {hls_playlist_status}\n\tStream info:"
            f" {stream_info_status}\n\tRequired keys: {required_keys}\n\tMissing keys:"
            f" {missing_keys}"
        )
