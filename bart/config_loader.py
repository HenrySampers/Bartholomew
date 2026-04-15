import json
import re
from pathlib import Path


CONFIG_PATH = Path("config") / "bart_config.json"


class BartConfig:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.data = self._load()

    def _load(self):
        if not self.path.exists():
            return {"apps": {}, "folders": {}, "websites": {}, "projects": {}, "routines": {}}
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _normalize(self, name):
        return re.sub(r"[^a-z0-9 ]", "", name.strip().lower()).strip()

    def get_app(self, name):
        return self.data.get("apps", {}).get(self._normalize(name))

    def get_folder(self, name):
        return self.data.get("folders", {}).get(self._normalize(name))

    def get_project(self, name):
        return self.data.get("projects", {}).get(self._normalize(name))

    def get_website(self, name):
        return self.data.get("websites", {}).get(self._normalize(name))

    def get_routine(self, name):
        return self.data.get("routines", {}).get(self._normalize(name))

    def describe_names(self):
        apps = ", ".join(sorted(self.data.get("apps", {}).keys())) or "none"
        folders = ", ".join(sorted(self.data.get("folders", {}).keys())) or "none"
        websites = ", ".join(sorted(self.data.get("websites", {}).keys())) or "none"
        projects = ", ".join(sorted(self.data.get("projects", {}).keys())) or "none"
        routines = ", ".join(sorted(self.data.get("routines", {}).keys())) or "none"
        return f"Apps: {apps}\nFolders: {folders}\nWebsites: {websites}\nProjects: {projects}\nRoutines: {routines}"
