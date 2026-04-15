"""
create_shortcut.py — Create a Windows desktop shortcut for Bart's UI.

Run once:
    python create_shortcut.py

This places a "Bartholomew.lnk" shortcut on your Desktop that launches
bart_ui.py using the current Python interpreter, with the project directory
as the working directory.
"""
import os
import subprocess
import sys
from pathlib import Path


def create():
    project_dir = Path(__file__).parent.resolve()
    python_exe = sys.executable
    script = project_dir / "bart_ui.py"
    icon = project_dir / "assets" / "bart.ico"
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / "Bartholomew.lnk"

    # Generate the icon now if it doesn't exist yet
    if not icon.exists():
        try:
            from bart.generate_icon import generate
            generate()
            print(f"[icon] generated {icon}")
        except Exception as e:
            print(f"[icon] could not generate icon: {e}")

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('{shortcut_path}')
$lnk.TargetPath = '{python_exe}'
$lnk.Arguments = '"{script}"'
$lnk.WorkingDirectory = '{project_dir}'
$lnk.Description = 'Bartholomew (Bart) AI Assistant'
"""
    if icon.exists():
        ps_script += f"$lnk.IconLocation = '{icon}'\n"
    ps_script += "$lnk.Save()\n"

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"[shortcut] created: {shortcut_path}")
    else:
        print(f"[shortcut] error: {result.stderr.strip()}")


if __name__ == "__main__":
    create()
