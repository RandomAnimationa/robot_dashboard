"""
Simple estimate of the robot's position/orientation from the wheel speeds
sent (dead-reckoning). This is only used to animate the on-screen silhouette,
it is not a real position (no encoders or IMU).
"""

import math


class DiffDriveEstimator:
    def __init__(self, track_width_m=0.14, max_speed_mps=0.5):
        """
        track_width_m: distance between wheels (approximate, adjustable).
        max_speed_mps: estimated linear speed when PWM = 255.
        """
        self.track_width = track_width_m
        self.max_speed = max_speed_mps
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0  # radians

    def reset(self):
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0

    def update(self, left_pwm, right_pwm, dt):
        v_l = (left_pwm / 255.0) * self.max_speed
        v_r = (right_pwm / 255.0) * self.max_speed

        v = (v_l + v_r) / 2.0
        omega = (v_r - v_l) / self.track_width

        self.x += v * math.cos(self.theta) * dt
        self.y += v * math.sin(self.theta) * dt
        self.theta += omega * dt
        self.theta = (self.theta + math.pi) % (2 * math.pi) - math.pi
