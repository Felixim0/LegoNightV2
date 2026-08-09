# LegoNight V2 — TODO

---

## 1. Dynamic speed scaling based on face box size

**Goal:** When the crosshair is inside the face box, scale motor power and step size
dynamically based on how large the box is on screen.

- Larger box = face is closer → allow higher fine-adjustment power (more confident position)
- Smaller box = face is further away → reduce power and step (more cautious, less overshoot)
- Derive a `box_area_ratio = (w * h) / (frame_w * frame_h)` and map it to a power range
- Replace the fixed `WHEN_IN_FACE_BOX` constants with a calculated value each frame
- Tune min/max bounds so it never drops below usable torque or exceeds safe speed

**Files to change:** `camera.py` (dispatch section), `motors.py` (consider adding a helper)

---

## 2. Firing mechanism via Motor C

**Goal:** When the countdown reaches zero and the target is acquired, trigger a firing
action on Motor C via the NXT brick.

- Requires a physical adaptor connecting the firing mechanism to Motor C port
- Add `MOTOR_FIRE_PORT = nxt.motor.Port.C` and a `fire()` function to `motors.py`
- `fire()` should: run Motor C for a fixed duration / degrees, then stop
- Add a `FIRE_POWER` and `FIRE_DEGREES` setting
- Trigger `fire()` once in `camera.py` when `fire_countdown_start` is set and
  `now - fire_countdown_start >= COUNTDOWN_START`
- Add a cooldown so it only fires once per acquisition, not on every frame at zero
- Gate behind `motors_enabled` flag so it's skipped in sim mode

**Files to change:** `motors.py` (add `fire()`), `camera.py` (trigger on countdown expiry)

---

## 3. Faster, more "live" face tracking

**Goal:** Make the tracking feel real-time — face detection updates as fast as possible
and motor commands follow with minimal lag.

- Reduce `DISPATCH_INTERVAL` (currently `0.1`) — try `0.05` or even `0.0`
- Run MediaPipe detection on a **separate thread** so it doesn't stall the camera loop;
  share the latest result via a thread-safe variable
- Consider dropping frame resolution for detection (e.g. scale down to 320×240 for
  MediaPipe, keep full res for display) — dramatically speeds up inference
- Profile with `time.time()` around the detection call to see actual bottleneck
- Reduce `motor.turn()` `time.sleep(1)` if the NXT allows shorter pulses — test with
  `0.3`–`0.5` s to see if steps complete reliably at shorter durations

**Files to change:** `camera.py` (threading for detection, interval tuning), `motors.py`
(sleep duration)
