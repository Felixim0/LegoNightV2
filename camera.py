"""
camera.py — Face detection, HUD overlay, and motor dispatch.

macOS requires cv2.imshow() on the main thread, so run() is blocking.
Motor commands go through two persistent queues (one per axis) so the
camera loop is NEVER stalled — horizontal and vertical can fire together.
"""

import functools
import queue
import threading
import time

import cv2

# MediaPipe gives far better accuracy than Haar cascades.
# Install once: pip install mediapipe
try:
    import mediapipe as mp
    _mp_face_detection = mp.solutions.face_detection
    _MEDIAPIPE = True
except ImportError:
    _MEDIAPIPE = False

from motors import (LEFT_RIGHT_POWER_WHEN_IN_FACE_BOX,
                    LEFT_RIGHT_POWER_WHEN_NOT_IN_FACE_BOX,
                    LEFT_RIGHT_STEP_WHEN_IN_FACE_BOX,
                    LEFT_RIGHT_STEP_WHEN_NOT_IN_FACE_BOX,
                    UP_DOWN_POWER_WHEN_IN_FACE_BOX,
                    UP_DOWN_POWER_WHEN_NOT_IN_FACE_BOX,
                    UP_DOWN_STEP_WHEN_IN_FACE_BOX,
                    UP_DOWN_STEP_WHEN_NOT_IN_FACE_BOX, moveDown, moveLeft,
                    moveRight, moveUp, shutdown)

# ----------------------------
# Settings
# ----------------------------
CAMERA_INDEX           = 0
PRINT_HZ               = 0.5    # terminal log lines per second
OVERLAY_ALPHA          = 0.35   # red overlay strength (0 = none, 1 = fully red)
OVERLAY_UPDATE_SECONDS = 2      # how often the on-screen TARGET label refreshes
TOLERANCE              = 15     # dead-zone radius in pixels — small so camera aims for exact face centre
WINDOW_NAME            = 'Guardian Vision V2'
UI_SCALE               = 1.4
COUNTDOWN_START        = 6      # seconds for 'firing in' countdown when crosshair is inside face box
DISPATCH_INTERVAL      = 0.1    # minimum seconds between queue additions per axis

GHOST_MAX_ACTIONS    = 4    # motor actions allowed on last-known position before ghost expires
SENTRY_STEPS_PER_DIR = 5    # steps in each direction during sentry sweep before reversing
SENTRY_INTERVAL      = 1.2  # seconds between sentry motor commands

BOX_COLOR       = (0, 255, 255)   # yellow — live detected face (BGR)
GHOST_BOX_COLOR = (0, 140, 255)   # orange — last known position, face not currently detected
BOX_THICKNESS = 2

# ----------------------------
# Non-blocking motor queues
# ----------------------------
# Two queues: horizontal and vertical.  Each has a single worker thread so
# X and Y motors can run at the same time without blocking each other or
# the camera loop.
#
# Queue behaviour:
#   - Holds up to MAX_QUEUE_SIZE pending commands.
#   - If a new command arrives and the queue is already full, the entire
#     queue is wiped and replaced with just the latest instruction.
#     This prevents the camera chasing a stale path after a big movement.

MAX_QUEUE_SIZE = 4

_hqueue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
_vqueue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)

# Mirror lists used only for HUD display — one entry per pending command.
# Protected by _display_lock since worker threads write and main thread reads.
_display_lock = threading.Lock()
_h_display: list = []
_v_display: list = []
_h_current: list = [None]   # single-element list so worker can mutate it (h axis)
_v_current: list = [None]   # single-element list so worker can mutate it (v axis)


def _worker(q: queue.Queue, display_list: list, current_ref: list) -> None:
    while True:
        item = q.get()
        if item is None:   # shutdown signal
            break
        action, display_name = item
        with _display_lock:
            if display_list:
                display_list.pop(0)      # move from pending → currently executing
            current_ref[0] = display_name
        action()
        with _display_lock:
            current_ref[0] = None        # done executing


def _dispatch(action, q: queue.Queue, display_list: list, enabled: bool) -> None:
    """Non-blocking put. Wipes the queue and restarts if it hits MAX_QUEUE_SIZE."""
    # getattr handles functools.partial (no __name__) gracefully
    display_name = getattr(action, '__name__', 'move').replace('move', '').upper()

    if not enabled:
        _dn = display_name
        def sim(_dn=_dn):
            print(f'[sim] {_dn}')
            time.sleep(1)   # mirrors real motor timing so the queue behaves identically
        action = sim

    if q.full():
        # Queue backed up — discard stale path and start fresh
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break
        with _display_lock:
            display_list.clear()

    try:
        q.put_nowait((action, display_name))
        with _display_lock:
            display_list.append(display_name)
    except queue.Full:
        pass  # safety net for race conditions


# ----------------------------
# Main camera function
# ----------------------------

def run(motors_enabled: bool = True) -> None:
    """Run the camera + HUD loop. Must be called from the main thread on macOS."""

    # Start the two motor worker threads before touching the camera
    threading.Thread(target=_worker, args=(_hqueue, _h_display, _h_current), daemon=True, name='motor-h').start()
    threading.Thread(target=_worker, args=(_vqueue, _v_display, _v_current), daemon=True, name='motor-v').start()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print('[camera] ERROR: could not open webcam.')
        return

    if _MEDIAPIPE:
        # model_selection=1 — full-range model, accurate up to ~5 m
        detector = _mp_face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.6
        )
        detector_type = 'mediapipe'
        print('[camera] Using MediaPipe face detector (high accuracy).')
    else:
        detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        detector_type = 'haar'
        print('[camera] MediaPipe not installed — falling back to Haar cascade.')
        print('[camera] For better accuracy run: pip install mediapipe')

    def put(text, pos, scale=1.0, thickness=2, color=(255, 255, 255)):
        cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                    scale * UI_SCALE, color, max(2, int(thickness * UI_SCALE)), cv2.LINE_AA)

    print_interval          = 1 / PRINT_HZ
    last_print_time         = 0.0
    last_instruction_update = 0.0

    current_instruction = 'NO TARGET'
    display_instruction = 'NO TARGET'
    instruction_history = []

    fire_countdown_start = None   # set when crosshair enters the face box; None = not counting
    in_face_box          = False  # updated each frame; drives overlay colour + countdown

    # Per-axis throttle: track when we last added to each queue
    last_h_dispatch = 0.0
    last_v_dispatch = 0.0

    last_face         = None   # (x, y, w, h) of the most recently detected face
    last_manual_input = 0.0    # timestamp of last WASD key press (for HUD indicator)

    # Camera mode state machine
    cam_mode      = 'TRACKING'  # 'TRACKING' | 'GHOST' | 'SENTRY'
    ghost_actions = 0           # motor dispatches used while ghost box is shown
    sentry_dir    = 'LEFT'      # current sentry sweep direction
    sentry_steps  = 0           # steps taken in current direction
    last_sentry   = 0.0         # last sentry dispatch timestamp

    mode_label = '' if motors_enabled else ' (SIM)'
    font       = cv2.FONT_HERSHEY_SIMPLEX
    qscale     = 0.6 * UI_SCALE
    qthick     = max(2, int(2 * UI_SCALE))
    GREEN      = (0, 220, 0)

    def draw_queue_line(label, current, pending, y):
        """Render one motor queue row: label (white), current (green), pending (white)."""
        (lw, _), _ = cv2.getTextSize(label, font, qscale, qthick)
        put(label, (20, y), scale=0.6)
        x = 20 + lw + 6
        if current:
            cv2.putText(frame, current, (x, y), font, qscale, GREEN, qthick, cv2.LINE_AA)
            (cw, _), _ = cv2.getTextSize(current, font, qscale, qthick)
            x += cw + 6
        if pending:
            sep = '  >  ' if current else ''
            put(sep + ' > '.join(pending), (x, y), scale=0.6)
        elif not current:
            put('--', (x, y), scale=0.6)

    print(f'[camera] {WINDOW_NAME} running — press Q to quit.')

    while True:
        ok, frame = cap.read()
        if not ok:
            print('[camera] Could not read from webcam.')
            break

        now = time.time()
        frame_h, frame_w = frame.shape[:2]
        frame_cx = frame_w // 2
        frame_cy = frame_h // 2

        # --- Full-screen overlay: green normally, red when crosshair is inside the face box ---
        # Uses last frame's in_face_box (one frame behind — imperceptible)
        _overlay = frame.copy()
        _overlay_color = (0, 0, 255) if in_face_box else (0, 200, 0)  # BGR: red | green
        cv2.rectangle(_overlay, (0, 0), (frame_w, frame_h), _overlay_color, -1)
        cv2.addWeighted(_overlay, OVERLAY_ALPHA, frame, 1 - OVERLAY_ALPHA, 0, frame)

        # --- Face detection ---
        if detector_type == 'mediapipe':
            rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb)
            faces   = []
            if results.detections:
                for det in results.detections:
                    bb = det.location_data.relative_bounding_box
                    fx = max(0, int(bb.xmin * frame_w))
                    fy = max(0, int(bb.ymin * frame_h))
                    fw = int(bb.width  * frame_w)
                    fh = int(bb.height * frame_h)
                    faces.append((fx, fy, fw, fh))
        else:
            grey  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            eq    = cv2.equalizeHist(grey)
            found = detector.detectMultiScale(
                eq, scaleFactor=1.05, minNeighbors=4, minSize=(40, 40)
            )
            faces = list(found) if len(found) else []

        terminal_message = 'NO TARGET'
        terminal_offset  = 'offset=(n/a)'

        if len(faces) > 0:
            # Live face detected
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            last_face = (x, y, w, h)
            if cam_mode != 'TRACKING':
                cam_mode      = 'TRACKING'
                ghost_actions = 0
            cv2.rectangle(frame, (x, y), (x + w, y + h), BOX_COLOR, BOX_THICKNESS)
            face_live = True
        else:
            if cam_mode == 'TRACKING':
                # Just lost the face — start ghost countdown
                cam_mode      = 'GHOST'
                ghost_actions = 0
            if cam_mode == 'GHOST' and last_face is not None:
                x, y, w, h = last_face
                cv2.rectangle(frame, (x, y), (x + w, y + h), GHOST_BOX_COLOR, BOX_THICKNESS)
            face_live = False

        if cam_mode in ('TRACKING', 'GHOST') and last_face is not None:
            x, y, w, h = last_face
            face_cx = x + w // 2
            face_cy = y + h // 2
            dx = face_cx - frame_cx
            dy = face_cy - frame_cy

            # Is the crosshair already inside the face box? Use slower power + brake if so.
            h_in_box    = (x <= frame_cx <= x + w)
            v_in_box    = (y <= frame_cy <= y + h)
            in_face_box = h_in_box and v_in_box and cam_mode == 'TRACKING'

            # Manage firing countdown
            if in_face_box:
                if fire_countdown_start is None:
                    fire_countdown_start = now
            else:
                fire_countdown_start = None
            h_power  = LEFT_RIGHT_POWER_WHEN_IN_FACE_BOX if h_in_box else LEFT_RIGHT_POWER_WHEN_NOT_IN_FACE_BOX
            v_power  = UP_DOWN_POWER_WHEN_IN_FACE_BOX    if v_in_box else UP_DOWN_POWER_WHEN_NOT_IN_FACE_BOX
            h_step   = LEFT_RIGHT_STEP_WHEN_IN_FACE_BOX  if h_in_box else LEFT_RIGHT_STEP_WHEN_NOT_IN_FACE_BOX
            v_step   = UP_DOWN_STEP_WHEN_IN_FACE_BOX     if v_in_box else UP_DOWN_STEP_WHEN_NOT_IN_FACE_BOX
            # Inside box → brake (precise stop); outside box → coast (don't waste time braking)
            h_brake  = h_in_box
            v_brake  = v_in_box

            def _bound(fn, power, step, brake):
                """Bind power + step + brake to a motor function, preserving its name for the HUD."""
                wrapped = functools.partial(fn, power=power, step=step, brake=brake)
                wrapped.__name__ = fn.__name__
                return wrapped

            x_instruction = None
            y_instruction = None
            h_dispatched  = False
            v_dispatched  = False

            if dx < -TOLERANCE:
                x_instruction = 'LEFT'
                if now - last_h_dispatch >= DISPATCH_INTERVAL:
                    _dispatch(_bound(moveLeft, h_power, h_step, h_brake), _hqueue, _h_display, motors_enabled)
                    last_h_dispatch = now
                    h_dispatched = True
            elif dx > TOLERANCE:
                x_instruction = 'RIGHT'
                if now - last_h_dispatch >= DISPATCH_INTERVAL:
                    _dispatch(_bound(moveRight, h_power, h_step, h_brake), _hqueue, _h_display, motors_enabled)
                    last_h_dispatch = now
                    h_dispatched = True
            else:
                while not _hqueue.empty():
                    try: _hqueue.get_nowait()
                    except queue.Empty: break
                with _display_lock: _h_display.clear()

            if dy < -TOLERANCE:
                y_instruction = 'UP'
                if now - last_v_dispatch >= DISPATCH_INTERVAL:
                    _dispatch(_bound(moveUp, v_power, v_step, v_brake), _vqueue, _v_display, motors_enabled)
                    last_v_dispatch = now
                    v_dispatched = True
            elif dy > TOLERANCE:
                y_instruction = 'DOWN'
                if now - last_v_dispatch >= DISPATCH_INTERVAL:
                    _dispatch(_bound(moveDown, v_power, v_step, v_brake), _vqueue, _v_display, motors_enabled)
                    last_v_dispatch = now
                    v_dispatched = True
            else:
                while not _vqueue.empty():
                    try: _vqueue.get_nowait()
                    except queue.Empty: break
                with _display_lock: _v_display.clear()

            # Count ghost actions and expire ghost box after limit
            if cam_mode == 'GHOST':
                ghost_actions += (1 if h_dispatched else 0) + (1 if v_dispatched else 0)
                if ghost_actions >= GHOST_MAX_ACTIONS:
                    cam_mode  = 'SENTRY'
                    last_face = None
                    for q in (_hqueue, _vqueue):
                        while not q.empty():
                            try: q.get_nowait()
                            except queue.Empty: break

            if x_instruction is None and y_instruction is None:
                current_instruction = 'ACQUIRED' if face_live else 'LAST KNOWN'
            elif x_instruction and y_instruction:
                current_instruction = x_instruction if abs(dx) >= abs(dy) else y_instruction
            else:
                current_instruction = x_instruction or y_instruction

            terminal_message = current_instruction
            terminal_offset  = f'offset=({dx}, {dy})'

        elif cam_mode == 'SENTRY':
            in_face_box          = False
            fire_countdown_start = None
            # Sweep left and right slowly until a face reappears
            if now - last_sentry >= SENTRY_INTERVAL:
                action = moveLeft if sentry_dir == 'LEFT' else moveRight
                _dispatch(action, _hqueue, _h_display, motors_enabled)
                last_sentry   = now
                sentry_steps += 1
                if sentry_steps >= SENTRY_STEPS_PER_DIR:
                    sentry_steps = 0
                    sentry_dir   = 'RIGHT' if sentry_dir == 'LEFT' else 'LEFT'
            current_instruction = 'SENTRY'

        else:
            in_face_box          = False
            fire_countdown_start = None
            current_instruction  = 'NO TARGET'

        # --- Rate-limited terminal log ---
        if now - last_print_time >= print_interval:
            print(f'{terminal_message} | '
                  f'frame_centre=({frame_cx}, {frame_cy}) | '
                  f'{terminal_offset}')
            last_print_time = now

        # --- Refresh displayed instruction every N seconds ---
        if now - last_instruction_update >= OVERLAY_UPDATE_SECONDS:
            display_instruction = current_instruction
            instruction_history.append(f'{current_instruction} {terminal_offset}')
            instruction_history = instruction_history[-5:]
            last_instruction_update = now

        # --- White centre crosshair ---
        cs = 20
        cv2.line(frame, (frame_cx - cs, frame_cy), (frame_cx + cs, frame_cy), (255, 255, 255), 2)
        cv2.line(frame, (frame_cx, frame_cy - cs), (frame_cx, frame_cy + cs), (255, 255, 255), 2)

        # --- HUD text ---

        # Top-centre: SCAN MODE
        scan_text = 'SCAN MODE'
        (tw, _), _ = cv2.getTextSize(scan_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0 * UI_SCALE, 2)
        put(scan_text, ((frame_w - tw) // 2, 40))

        # Top-centre below title: WASD hint
        put('W/A/S/D: manual control   Q: quit', ((frame_w - tw) // 2 - 60, 70), scale=0.5, color=(180, 180, 180))

        # Top-left: current target instruction
        put(f'TARGET: {display_instruction}', (20, 90))

        # Top-right: manual control indicator (shown for 1 s after last key press)
        if now - last_manual_input < 1.0:
            manual_text = 'MANUAL CONTROL'
            (mw, _), _ = cv2.getTextSize(manual_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7 * UI_SCALE, 2)
            put(manual_text, (frame_w - mw - 20, 40), scale=0.7, color=(0, 220, 255))

        # Mid-left: last 5 instructions with offsets
        hy = frame_h // 2 - int(90 * UI_SCALE)
        for i, entry in enumerate(instruction_history):
            put(entry, (20, hy + i * int(35 * UI_SCALE)), scale=0.7)

        # Bottom-left: motor queue display
        with _display_lock:
            h_current = _h_current[0]
            v_current = _v_current[0]
            h_pending = list(_h_display)
            v_pending = list(_v_display)

        draw_queue_line(f'PAN{mode_label}:',  h_current, h_pending, frame_h - 110)
        draw_queue_line(f'TILT{mode_label}:', v_current, v_pending, frame_h - 75)

        # Bottom-left: firing countdown (only when crosshair is locked inside face box)
        if fire_countdown_start is not None:
            remaining = max(0.0, COUNTDOWN_START - (now - fire_countdown_start))
            put(f'firing in {remaining:.0f}', (20, frame_h - 30), scale=3.5, thickness=4, color=(0, 0, 255))

        cv2.imshow(WINDOW_NAME, frame)

        # --- Key handling ---
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break

        def _clear_and_dispatch(action, q, display_list):
            """Flush queue and insert manual command at front (highest priority)."""
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
            with _display_lock:
                display_list.clear()
            _dispatch(action, q, display_list, motors_enabled)

        # WASD manual control
        if key == ord('a'):
            _clear_and_dispatch(moveLeft,  _hqueue, _h_display)
            last_manual_input = now
        elif key == ord('d'):
            _clear_and_dispatch(moveRight, _hqueue, _h_display)
            last_manual_input = now
        elif key == ord('w'):
            _clear_and_dispatch(moveUp,    _vqueue, _v_display)
            last_manual_input = now
        elif key == ord('s'):
            _clear_and_dispatch(moveDown,  _vqueue, _v_display)
            last_manual_input = now

    # --- Cleanup ---
    # Drain queues first so no stale commands run after quit
    for q in (_hqueue, _vqueue):
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break

    cap.release()
    cv2.destroyAllWindows()
    if detector_type == 'mediapipe':
        detector.close()

    # Stop motors before sending shutdown signal to workers
    if motors_enabled:
        shutdown()

    _hqueue.put(None)
    _vqueue.put(None)
    print('[camera] Closed.')
