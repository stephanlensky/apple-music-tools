import xml.etree.ElementTree as ET
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


class SongDownloadFlow(BaseModel):
    id: int  # arbitrary, not from Apple. used internally
    playback_dispatch: str
    hls_playlist: Optional[str]
    selected_hls_stream_info: Optional[str]
    keys: dict[str, str] = {}  # keyUri -> ckc

    @validator("playback_dispatch")
    @classmethod
    def validate_playback_dispatch(cls, v):
        # if this throws an exception, the playback dispatch is not valid
        cls.__get_hls_playlist_url_from_playback_dispatch(v)
        return v

    @property
    def hls_playlist_url(self) -> str:
        """Parse the HLS playlist URL from the playback dispatch XML."""
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
            required_key_uris.remove(key_uri)
        return required_key_uris
