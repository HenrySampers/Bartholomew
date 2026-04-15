"""Weather via wttr.in — no API key required."""
import os
import urllib.request
import urllib.parse


def weather():
    location = os.getenv("WEATHER_LOCATION", "").strip()
    try:
        loc = urllib.parse.quote(location) if location else ""
        url = f"https://wttr.in/{loc}?format=3"
        with urllib.request.urlopen(url, timeout=8) as resp:
            result = resp.read().decode("utf-8").strip()
        if not result:
            return "couldn't get the weather bro, wttr.in came back empty."
        return result
    except Exception as exc:
        return f"can't reach the weather service rn bro: {exc}"
