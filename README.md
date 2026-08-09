# LegoNight V2 — Face-Tracking Security Camera

A Python program that opens your webcam, finds your face,
draws a yellow box around it, and tells the camera which way to move.

---

## What it does

- Opens the webcam and shows a live preview window
- Detects your face using OpenCV's built-in face detector
- Draws a **yellow rectangle** around the face
- If your face is off-centre, it calls one of four motor functions:
  `moveLeft`, `moveRight`, `moveUp`, `moveDown`
- The motor functions just **print a direction** for now — real motor code goes in later

---

## Files

| File | What it does |
|---|---|
| `main.py` | Start here. Launches the program. |
| `camera.py` | Runs the webcam and face detection. |
| `motors.py` | The four movement functions. Edit these to add motor code. |

---

## How to install and run

**1. Install the one dependency**
```bash
pip install opencv-python
```

**2. Run the program**
```bash
python main.py
```

**3. To quit** — press **Q** in the camera window, or **Ctrl-C** in the terminal.

---

## How to add motor code later

Open `motors.py` and replace the `print` statements with your motor logic:

```python
def moveLeft():
    # your motor code here
    print("left")
```

Each function is called in its own background thread, so slow motor
commands will never freeze the camera preview.

---

## How the threading works (simple version)

macOS requires that any window (like the camera preview) runs on the **main thread**.

So the design is:
- **Main thread** → runs the camera preview (required by macOS)
- **Background threads** → run motor commands (so they don't freeze the camera)

To add your own background logic, add it to `_background_worker()` in `main.py`.

---

## Tuning the dead zone

In `camera.py`, the `DEAD_ZONE` value controls how far off-centre the face
must be before a motor command is triggered.

```python
DEAD_ZONE = 0.2   # 20% from centre on each side = neutral zone
```

Increase it to make the system less twitchy. Decrease it for faster reactions.
