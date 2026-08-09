"""
main.py — Entry point.

Usage:
  python main.py                  # normal run, motors enabled
  python main.py motors=disabled  # camera-only, no motor commands sent
"""

import sys
import threading

import camera


# ---------------------------------------------------------------------------
# Example background worker — replace / extend with real motor logic later.
# ---------------------------------------------------------------------------
def _background_worker():
    """Placeholder for motor controllers or other logic."""


def main():
    motors_enabled = 'motors=disabled' not in sys.argv

    if not motors_enabled:
        print('[main] Motors DISABLED (camera-only mode).')

    threading.Thread(target=_background_worker, daemon=True, name='worker').start()

    try:
        camera.run(motors_enabled=motors_enabled)
    except KeyboardInterrupt:
        print('\n[main] Shutting down...')


if __name__ == "__main__":
    main()
