"""python -m sheetmusic <gui | bot | parts | a3> [options]"""

import sys

USAGE = """usage: python -m sheetmusic <command> [options]

commands:
  gui     desktop app (needs the 'gui' extra)
  bot     Telegram bot (needs the 'bot' extra; reads TELEGRAM_BOT_TOKEN)
  parts   split a PDF into score and instrument parts
  a3      A3 -> A4 split + contrast + rename

'python -m sheetmusic <command> --help' shows the options of a command."""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 1
    command, rest = argv[0], argv[1:]
    if command == "gui":
        from .gui.main_window import main as run
        return run(rest) or 0
    if command == "bot":
        from .bot.app import main as run
        return run() or 0
    if command in ("parts", "a3"):
        from . import cli
        return (cli.parts_main if command == "parts" else cli.a3_main)(rest)
    print(f"unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
