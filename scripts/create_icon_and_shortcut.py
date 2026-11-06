"""
OpenChromLab Icon and Windows Shortcut Generator.

Generates:
1. OpenChromLab.ico: Multi-tier chromatography artwork icon in workspace root.
2. OpenChromLab.lnk: Windows shortcut pointing to Run_OpenChromLab.bat with OpenChromLab.ico.
"""

import os
import subprocess
import sys


def main() -> int:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.dirname(scripts_dir)
    ps1_script = os.path.join(scripts_dir, "create_icon_and_shortcut.ps1")

    if not os.path.exists(ps1_script):
        print(f"Error: PowerShell script '{ps1_script}' not found.", file=sys.stderr)
        return 1

    print(f"Executing icon & shortcut generator: {ps1_script}")
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        ps1_script,
        "-WorkspaceRoot",
        workspace_root,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"PowerShell generator failed with code {res.returncode}:", file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        print(res.stdout)
        return res.returncode

    print(res.stdout)

    # Verification
    ico_path = os.path.join(workspace_root, "OpenChromLab.ico")
    lnk_path = os.path.join(workspace_root, "OpenChromLab.lnk")

    if not os.path.exists(ico_path):
        print(f"Error: Expected icon '{ico_path}' does not exist.", file=sys.stderr)
        return 1
    ico_size = os.path.getsize(ico_path)
    if ico_size < 1000:
        print(f"Error: Icon file size too small ({ico_size} bytes).", file=sys.stderr)
        return 1
    print(f"Verified {ico_path} ({ico_size} bytes).")

    if not os.path.exists(lnk_path):
        print(f"Error: Expected shortcut '{lnk_path}' does not exist.", file=sys.stderr)
        return 1
    lnk_size = os.path.getsize(lnk_path)
    if lnk_size == 0:
        print(f"Error: Shortcut file is empty ({lnk_size} bytes).", file=sys.stderr)
        return 1
    print(f"Verified {lnk_path} ({lnk_size} bytes).")

    # Verify Tkinter loading
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.iconbitmap(ico_path)
        r.destroy()
        print("Verified Tkinter iconbitmap compatibility: OK.")
    except Exception as exc:
        print(f"Warning: Tkinter iconbitmap test exception: {exc}")

    print("OpenChromLab icon and shortcut generation completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
