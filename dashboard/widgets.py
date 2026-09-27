"""
Minimal pygame UI widgets: buttons, keyboard-editable number and text
fields, and a simple selectable list.
No dependency beyond pygame itself.
"""

import pygame

FONT_NAME = None  # default system font


def get_font(size=20, bold=False):
    f = pygame.font.SysFont(FONT_NAME, size, bold=bold)
    return f


class Button:
    def __init__(self, rect, label, callback=None, color=(60, 60, 70), text_color=(230, 230, 230)):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.callback = callback
        self.color = color
        self.text_color = text_color
        self.hover = False
        self.enabled = True

    def handle_event(self, event):
        if not self.enabled:
            return
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and self.callback:
                self.callback()

    def draw(self, surface, font=None):
        font = font or get_font(18)
        color = tuple(min(255, c + 25) for c in self.color) if self.hover else self.color
        if not self.enabled:
            color = (40, 40, 45)
        pygame.draw.rect(surface, color, self.rect, border_radius=6)
        pygame.draw.rect(surface, (20, 20, 25), self.rect, 1, border_radius=6)
        text_surf = font.render(self.label, True, self.text_color if self.enabled else (110, 110, 110))
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)


class NumberField:
    """Number field: click to edit with the keyboard, or use the -/+ buttons."""

    def __init__(self, rect, value=0, step=10, min_value=-255, max_value=255):
        self.rect = pygame.Rect(rect)
        self.value = value
        self.step = step
        self.min_value = min_value
        self.max_value = max_value
        self.editing = False
        self.buffer = ""

        minus_rect = (self.rect.x, self.rect.y, 28, self.rect.height)
        plus_rect = (self.rect.right - 28, self.rect.y, 28, self.rect.height)
        self.btn_minus = Button(minus_rect, "-", self._dec, color=(70, 40, 40))
        self.btn_plus = Button(plus_rect, "+", self._inc, color=(40, 70, 40))

    def _dec(self):
        self.value = max(self.min_value, self.value - self.step)

    def _inc(self):
        self.value = min(self.max_value, self.value + self.step)

    def handle_event(self, event):
        self.btn_minus.handle_event(event)
        self.btn_plus.handle_event(event)

        text_area = pygame.Rect(self.rect.x + 30, self.rect.y, self.rect.width - 60, self.rect.height)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if text_area.collidepoint(event.pos):
                self.editing = True
                self.buffer = str(self.value)
            else:
                if self.editing:
                    self._commit()
                self.editing = False

        elif event.type == pygame.KEYDOWN and self.editing:
            if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                self._commit()
                self.editing = False
            elif event.key == pygame.K_ESCAPE:
                self.editing = False
            elif event.key == pygame.K_BACKSPACE:
                self.buffer = self.buffer[:-1]
            elif event.unicode.isdigit() or (event.unicode == "-" and self.buffer == ""):
                self.buffer += event.unicode

    def _commit(self):
        try:
            v = int(self.buffer)
        except ValueError:
            v = self.value
        self.value = max(self.min_value, min(self.max_value, v))

    def draw(self, surface, font=None):
        font = font or get_font(18)
        self.btn_minus.draw(surface, font)
        self.btn_plus.draw(surface, font)
        text_area = pygame.Rect(self.rect.x + 30, self.rect.y, self.rect.width - 60, self.rect.height)
        pygame.draw.rect(surface, (25, 25, 30), text_area)
        pygame.draw.rect(surface, (80, 80, 90), text_area, 1)
        display_text = self.buffer if self.editing else str(self.value)
        text_surf = font.render(display_text, True, (240, 240, 240))
        surface.blit(text_surf, text_surf.get_rect(center=text_area.center))


class TextField:
    def __init__(self, rect, value=""):
        self.rect = pygame.Rect(rect)
        self.value = value
        self.editing = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.editing = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.editing:
            if event.key == pygame.K_RETURN or event.key == pygame.K_ESCAPE:
                self.editing = False
            elif event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.value += event.unicode

    def draw(self, surface, font=None):
        font = font or get_font(18)
        bg = (35, 35, 45) if self.editing else (25, 25, 30)
        pygame.draw.rect(surface, bg, self.rect)
        pygame.draw.rect(surface, (90, 90, 100), self.rect, 1)
        text_surf = font.render(self.value, True, (240, 240, 240))
        surface.blit(text_surf, (self.rect.x + 6, self.rect.y + (self.rect.height - text_surf.get_height()) // 2))


class SelectableList:
    """Simple list: each item is (key, label). Returns the selected key."""

    def __init__(self, rect, items, item_height=34):
        self.rect = pygame.Rect(rect)
        self.items = items  # list of (key, label)
        self.item_height = item_height
        self.selected = items[0][0] if items else None
        self.scroll = 0

    def set_items(self, items):
        self.items = items
        if self.selected not in [i[0] for i in items]:
            self.selected = items[0][0] if items else None

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                rel_y = event.pos[1] - self.rect.y + self.scroll
                idx = rel_y // self.item_height
                if 0 <= idx < len(self.items):
                    self.selected = self.items[idx][0]
        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - event.y * 20)

    def draw(self, surface, font=None):
        font = font or get_font(18)
        prev_clip = surface.get_clip()
        surface.set_clip(self.rect)
        pygame.draw.rect(surface, (20, 20, 25), self.rect)
        for i, (key, label) in enumerate(self.items):
            y = self.rect.y + i * self.item_height - self.scroll
            item_rect = pygame.Rect(self.rect.x, y, self.rect.width, self.item_height)
            if not self.rect.colliderect(item_rect):
                continue
            color = (55, 75, 100) if key == self.selected else (30, 30, 38)
            pygame.draw.rect(surface, color, item_rect)
            pygame.draw.rect(surface, (15, 15, 20), item_rect, 1)
            text_surf = font.render(label, True, (235, 235, 235))
            surface.blit(text_surf, (item_rect.x + 8, item_rect.y + (item_rect.height - text_surf.get_height()) // 2))
        surface.set_clip(prev_clip)
        pygame.draw.rect(surface, (80, 80, 90), self.rect, 1)
