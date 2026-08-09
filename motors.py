"""
motors.py — NXT motor control.

Motor A = left / right pan
Motor B = up / down tilt

Called from camera.py via the motor queues (one thread per axis).
"""


import time

# ----------------------------
# Settings
# ----------------------------
UP_DOWN_STEP     = 360
LEFT_RIGHT_STEP  = 30

# Power when crosshair is OUTSIDE the face box (fast approach)
LEFT_RIGHT_POWER_WHEN_NOT_IN_FACE_BOX = 30
UP_DOWN_POWER_WHEN_NOT_IN_FACE_BOX    = 100

# Power when crosshair is INSIDE the face box (slow fine-adjustment)
LEFT_RIGHT_POWER_WHEN_IN_FACE_BOX     = 15
UP_DOWN_POWER_WHEN_IN_FACE_BOX        = 40

# ----------------------------
# Hardware setup
# ----------------------------
# Wrapped in try/except so the module imports cleanly even when the NXT
# brick is not plugged in (e.g. running with motors=disabled).

try:
    import nxt.locator
    import nxt.motor

    MOTOR_LEFT_RIGHT_PORT = nxt.motor.Port.A
    MOTOR_UP_DOWN_PORT    = nxt.motor.Port.B

    brick   = nxt.locator.find()
    motor_a = brick.get_motor(MOTOR_LEFT_RIGHT_PORT)
    motor_b = brick.get_motor(MOTOR_UP_DOWN_PORT)
    _NXT_READY = True
    print('[motors] NXT brick connected.')
except Exception as _e:
    motor_a = None
    motor_b = None
    _NXT_READY = False
    print(f'[motors] NXT not available ({_e}). Hardware commands will be skipped.')

# ----------------------------
# Movement functions
# ----------------------------

def moveLeft(power=LEFT_RIGHT_POWER_WHEN_NOT_IN_FACE_BOX):
    if not _NXT_READY: return
    motor_a.turn(power, LEFT_RIGHT_STEP)
    time.sleep(1)


def moveRight(power=LEFT_RIGHT_POWER_WHEN_NOT_IN_FACE_BOX):
    if not _NXT_READY: return
    motor_a.turn(-power, LEFT_RIGHT_STEP)
    time.sleep(1)


def moveUp(power=UP_DOWN_POWER_WHEN_NOT_IN_FACE_BOX):
    if not _NXT_READY: return
    motor_b.turn(power, UP_DOWN_STEP)
    time.sleep(1)


def moveDown(power=UP_DOWN_POWER_WHEN_NOT_IN_FACE_BOX):
    if not _NXT_READY: return
    motor_b.turn(-power, UP_DOWN_STEP)
    time.sleep(1)


def shutdown():
    if not _NXT_READY: return
    print('[motors] Stopping motors...')
    for motor in (motor_a, motor_b):
        try:
            motor.brake()   # active stop — counters any remaining momentum
        except Exception:
            pass
        try:
            motor.idle()    # release the hold so the motor isn't locked
        except Exception:
            pass
    print('[motors] Done.')
