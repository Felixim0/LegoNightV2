"""
main.py — Entry point.

macOS requires OpenCV windows to live on the main thread, so camera.run()
is called directly here and blocks until the user quits.

Any background work (motors, networking, etc.) should be started as
daemon threads BEFORE calling camera.run(), exactly like the example
worker thread below.
"""

import threading

import camera


# ---------------------------------------------------------------------------
# Example background worker — replace / extend with real motor logic later.
# ---------------------------------------------------------------------------
def _background_worker():
    """Placeholder for motor controllers or other logic."""
    # This runs concurrently with the camera preview.


def main():
    # Start background workers first
    threading.Thread(target=_background_worker, daemon=True, name="worker").start()

    # Hand control to the camera loop (must stay on the main thread on macOS)
    try:
        camera.run()
    except KeyboardInterrupt:
        print("\n[main] Shutting down...")


if __name__ == "__main__":
    main()
