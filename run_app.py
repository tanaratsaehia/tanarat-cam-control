"""Nuitka/pyside6-deploy entry point — thin wrapper around camcontrol.app.main."""

from camcontrol.app import main

if __name__ == "__main__":
    raise SystemExit(main())
