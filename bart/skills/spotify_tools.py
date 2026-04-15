"""
Spotify API tools via spotipy.

Setup (one-time):
  1. Go to developer.spotify.com/dashboard and create an app.
  2. Set redirect URI to http://localhost:8888/callback in the app settings.
  3. Add to .env:
       SPOTIFY_CLIENT_ID=your_client_id
       SPOTIFY_CLIENT_SECRET=your_client_secret
  4. On first run, a browser window will open asking you to log in — do it once
     and spotipy caches the token automatically.
"""
import os


def _get_sp():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        return None, "spotipy isn't installed bro. run: pip install spotipy"

    client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None, "spotify credentials aren't set bro, check the .env file."

    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://localhost:8888/callback",
            scope="user-read-playback-state user-modify-playback-state user-read-currently-playing",
            open_browser=True,
            cache_path=".spotify_cache",
        ))
        return sp, None
    except Exception as exc:
        return None, f"spotify auth failed bro: {exc}"


def spotify_current() -> str:
    sp, err = _get_sp()
    if err:
        return err
    try:
        current = sp.current_playback()
        if not current or not current.get("is_playing"):
            return "nothing playing rn bro."
        track = current["item"]
        artist = track["artists"][0]["name"]
        song = track["name"]
        return f"playing {song} by {artist} bro."
    except Exception as exc:
        return f"couldn't reach spotify bro: {exc}"


def spotify_play_pause() -> str:
    sp, err = _get_sp()
    if err:
        return err
    try:
        current = sp.current_playback()
        if current and current.get("is_playing"):
            sp.pause_playback()
            return "paused bro."
        else:
            sp.start_playback()
            return "resumed bro."
    except Exception as exc:
        return f"spotify error bro: {exc}"


def spotify_next() -> str:
    sp, err = _get_sp()
    if err:
        return err
    try:
        sp.next_track()
        return "skipped bro."
    except Exception as exc:
        return f"spotify error bro: {exc}"


def spotify_prev() -> str:
    sp, err = _get_sp()
    if err:
        return err
    try:
        sp.previous_track()
        return "went back bro."
    except Exception as exc:
        return f"spotify error bro: {exc}"


def spotify_search_play(query: str) -> str:
    sp, err = _get_sp()
    if err:
        return err
    try:
        results = sp.search(q=query, limit=1, type="track")
        items = results["tracks"]["items"]
        if not items:
            return f"couldn't find '{query}' on spotify bro."
        track = items[0]
        uri = track["uri"]
        sp.start_playback(uris=[uri])
        return f"playing {track['name']} by {track['artists'][0]['name']} bro."
    except Exception as exc:
        return f"spotify error bro: {exc}"
