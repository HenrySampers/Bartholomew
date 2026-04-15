"""
Voice config editing: teach Bart new apps, folders, websites, and projects
without touching a single Python file.
config is bound by ToolRegistry via functools.partial.
"""


def add_app(config, name, target):
    config.data.setdefault("apps", {})[name.strip().lower()] = target.strip()
    config.save()
    return f"Understood, Sir. I will remember {name} as an application."


def remove_app(config, name):
    key = name.strip().lower()
    if key in config.data.get("apps", {}):
        del config.data["apps"][key]
        config.save()
        return f"Done, Sir. {name} has been removed from my applications."
    return f"I do not have {name!r} in my applications, Sir."


def add_folder(config, name, path):
    config.data.setdefault("folders", {})[name.strip().lower()] = path.strip()
    config.save()
    return f"Understood, Sir. I will remember {name} as a folder."


def remove_folder(config, name):
    key = name.strip().lower()
    if key in config.data.get("folders", {}):
        del config.data["folders"][key]
        config.save()
        return f"Done, Sir. {name} has been removed from my folders."
    return f"I do not have {name!r} in my folders, Sir."


def add_website(config, name, url):
    if not url.strip().startswith(("http://", "https://")):
        url = f"https://{url.strip()}"
    config.data.setdefault("websites", {})[name.strip().lower()] = url
    config.save()
    return f"Understood, Sir. I will remember {name} as a website."


def remove_website(config, name):
    key = name.strip().lower()
    if key in config.data.get("websites", {}):
        del config.data["websites"][key]
        config.save()
        return f"Done, Sir. {name} has been removed from my websites."
    return f"I do not have {name!r} in my websites, Sir."
