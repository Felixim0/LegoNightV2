"""
motors.py — NXT motor control.

Motor A = left / right pan
Motor B = up / down tilt

Called from camera.py via the motor queues (one thread per axis).
"""

import time

import nxt.locator
import nxt.motor

# ----------------------------
# Settings
# ----------------------------
UP_DOWN_STEP     = 360
LEFT_RIGHT_STEP  = 30

UP_DOWN_POWER    = 100
LEFT_RIGHT_POWER = 30

MOTOR_LEFT_RIGHT_PORT = nxt.motor.Port.A
MOTOR_UP_DOWN_PORT    = nxt.motor.Port.B

# ----------------------------
# Hardware setup
# ----------------------------
brick   = nxt.locator.find()
motor_a = brick.get_motor(MOTOR_LEFT_RIGHT_PORT)
motor_b = brick.get_motor(MOTOR_UP_DOWN_PORT)

# ----------------------------
# Movement functions
# ----------------------------

def moveLeft():
    motor_a.turn(LEFT_RIGHT_POWER, LEFT_RIGHT_STEP)
    time.sleep(1)


def moveRight():
    motor_a.turn(-LEFT_RIGHT_POWER, LEFT_RIGHT_STEP)
    time.sleep(1)


def moveUp():
    motor_b.turn(UP_DOWN_POWER, UP_DOWN_STEP)
    time.sleep(1)


def moveDown():
    motor_b.turn(-UP_DOWN_POWER, UP_DOWN_STEP)
    time.sleep(1)


def shutdown():
    """Stop both motors cleanly. Call on program exit.

    Sends brake() first to kill any momentum, then idle() to release the hold.
    """
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
