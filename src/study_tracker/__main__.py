"""Entry point – run with: python -m study_tracker"""

import sys


def main() -> None:
    # Import lazily so the module can be imported without a display.
    from study_tracker.app import Application

    app = Application(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
