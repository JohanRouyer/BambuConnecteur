# Privacy Policy

*Last updated: October 30, 2026*

Bambu Studio Advisor is a local MCP connector and Claude plugin. It runs entirely on your computer.
This policy explains what it handles, where it keeps it and who can see it.

## Data collection

The connector collects **no personal data** and has **no telemetry, analytics or tracking**. It
reads only what you ask Claude to work on:

- the 3D files (STL, 3MF) whose paths you give;
- your Bambu Studio presets and install folder, on your PC;
- your defaults (printer, build plate, usual filament), saved when you choose them;
- optionally, your printer's IP address, serial number and LAN access code, which you enter yourself.

## Usage and storage

- Files are analyzed and sliced locally with your own `bambu-studio.exe`.
- Results (`result.3mf` files, slice cache, `history.jsonl`) and your defaults (`config.json`) are
  stored on your PC: in the plugin's data folder (`~/.claude/plugins/data/…`) when installed as a
  Claude plugin, or in the project folder when run from a clone.
- The printer access code is stored in your system's secure credential store when entered in the
  plugin settings, or in `config.json` (excluded from git) when run from a clone.
- The printer connection is used only to **read** its status over your local network (MQTT over TLS
  to the printer's own IP). The connector never starts, stops or changes a print.

## Third-party sharing

The connector itself sends **nothing** to the developer or to any other server: it makes no internet
requests.

- **Claude**: the results of the tools (dimensions, print times, weights, settings, file paths) are
  returned to Claude, the app you are using, and processed under
  [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy).
- **Bambu Studio**: slicing runs your installed Bambu Studio, which follows
  [Bambu Lab's privacy policy](https://bambulab.com/en/policies/privacy).
- **Installation**: when the plugin starts for the first time, `uv` downloads the Python packages
  listed in `uv.lock` (and Python if needed) from PyPI and python.org.

## Data retention

Everything stays on your PC until you delete it. You can delete the `output` folder (results, cache,
history), `config.json` (defaults, printer connection) and `backups` (preset backups made before a
change) at any time. Uninstalling the Claude plugin deletes its data folder. The developer keeps no
data, because none is ever sent to them.

## Children

The connector is not directed at children under 13 and collects no data from anyone.

## Changes

Changes to this policy are published in this file, in the project's GitHub repository, with a new
date at the top.

## Contact

Questions or requests: open an issue at
<https://github.com/JohanRouyer/BambuStudio-Advisor-MCP/issues>.
