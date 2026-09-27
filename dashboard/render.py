"""
Draws the robot silhouette (top view) with a speed indicator for each wheel,
plus an optional trace of the estimated trajectory (dead-reckoning), and the
telemetry panel.
"""

import pygame
from widgets import get_font

WHEEL_COLOR_FWD = (60, 200, 90)
WHEEL_COLOR_REV = (210, 80, 70)
WHEEL_COLOR_IDLE = (90, 90, 95)


def _wheel_color(speed):
    if speed > 5:
        return WHEEL_COLOR_FWD
    if speed < -5:
        return WHEEL_COLOR_REV
    return WHEEL_COLOR_IDLE


def draw_silhouette(surface, rect, left_speed, right_speed, trail_points=None):
    """
    rect: area to draw into (pygame.Rect)
    left_speed/right_speed: -255..255
    trail_points: list of already-projected (x, y) screen points
    """
    pygame.draw.rect(surface, (18, 18, 22), rect, border_radius=8)
    pygame.draw.rect(surface, (60, 60, 70), rect, 1, border_radius=8)

    cx, cy = rect.center
    body_w, body_h = int(rect.width * 0.35), int(rect.height * 0.55)
    body_rect = pygame.Rect(0, 0, body_w, body_h)
    body_rect.center = (cx, cy)

    # estimated trajectory (optional)
    if trail_points and len(trail_points) > 1:
        pygame.draw.lines(surface, (70, 100, 140), False, trail_points, 2)

    # body
    pygame.draw.rect(surface, (40, 130, 130), body_rect, border_radius=10)
    pygame.draw.rect(surface, (15, 60, 60), body_rect, 2, border_radius=10)

    # "front" arrow of the robot
    front_y = body_rect.top + 10
    pygame.draw.polygon(
        surface, (230, 230, 100),
        [(cx, front_y - 8), (cx - 10, front_y + 8), (cx + 10, front_y + 8)]
    )

    # wheels
    wheel_w = max(14, int(body_w * 0.28))
    wheel_h = int(body_h * 0.5)

    left_rect = pygame.Rect(0, 0, wheel_w, wheel_h)
    left_rect.center = (body_rect.left - wheel_w // 2 + 2, cy)
    right_rect = pygame.Rect(0, 0, wheel_w, wheel_h)
    right_rect.center = (body_rect.right + wheel_w // 2 - 2, cy)

    pygame.draw.rect(surface, _wheel_color(left_speed), left_rect, border_radius=4)
    pygame.draw.rect(surface, (10, 10, 12), left_rect, 2, border_radius=4)
    pygame.draw.rect(surface, _wheel_color(right_speed), right_rect, border_radius=4)
    pygame.draw.rect(surface, (10, 10, 12), right_rect, 2, border_radius=4)

    font = get_font(16)
    l_label = font.render(f"{int(left_speed)}", True, (10, 10, 10))
    r_label = font.render(f"{int(right_speed)}", True, (10, 10, 10))
    surface.blit(l_label, l_label.get_rect(center=left_rect.center))
    surface.blit(r_label, r_label.get_rect(center=right_rect.center))


def draw_telemetry_panel(surface, rect, telemetry, stale):
    pygame.draw.rect(surface, (18, 18, 22), rect, border_radius=8)
    pygame.draw.rect(surface, (60, 60, 70), rect, 1, border_radius=8)

    font_title = get_font(20, bold=True)
    font = get_font(18)

    title_color = (200, 70, 70) if stale else (230, 230, 230)
    title = "TELEMETRY (no data)" if stale else "TELEMETRY"
    surface.blit(font_title.render(title, True, title_color), (rect.x + 12, rect.y + 10))

    lines = [
        f"Robot uptime: {telemetry.uptime_ms / 1000.0:.1f} s",
        f"RSSI: {telemetry.rssi} dBm",
        f"Connected clients: {telemetry.clients}",
        f"Battery: {telemetry.battery:.2f} V" if telemetry.battery > 0 else "Battery: not configured",
        f"Left wheel (reported): {telemetry.left}",
        f"Right wheel (reported): {telemetry.right}",
    ]
    y = rect.y + 42
    for line in lines:
        surface.blit(font.render(line, True, (210, 210, 210)), (rect.x + 12, y))
        y += 26
