"""Pygame visualizer separated from the decision engine."""
from __future__ import annotations

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
GLOBAL_HUD_HEIGHT = 50
FPS = 30


def _snake_palette(is_a):
    palette_a = ((50, 255, 100), (0, 160, 50), (60, 180, 255), (0, 80, 180))
    palette_b = ((60, 180, 255), (0, 80, 180), (50, 255, 100), (0, 160, 50))
    return palette_a if is_a else palette_b


def _food_color_map(food_digits):
    return dict.fromkeys(food_digits, (255, 170, 40))


def _side_colors(my_side, food_digits):
    p1_head, p1_body, p2_head, p2_body = _snake_palette(str(my_side).upper() in {"A", "1"})
    colors = {
        "*": (255, 90, 50), "#": (70, 70, 75),
        "A": p1_head, "a": p1_body,
        "B": p2_head, "b": p2_body,
    }
    colors.update(_food_color_map(food_digits))
    return colors


def _grid_layout(count):
    from bisect import bisect_left
    layouts = ((1, 1), (1, 2), (2, 2), (2, 3), (2, 4), (3, 4))
    return layouts[bisect_left((1, 2, 4, 6, 8), count)]


def _border_color(game):
    if not game["game_over"]:
        return (60, 60, 70)
    won = game.get("winner") and game["my_name"] in game["winner"]
    return (255, 215, 0) if won else (160, 50, 50)


def _draw_panel_header(pygame, screen, game, rect, fonts):
    font_bold, font_small = fonts
    x, y, w, _ = rect
    pygame.draw.rect(screen, (22, 22, 24), rect, border_radius=8)
    pygame.draw.rect(screen, _border_color(game), rect, 2, border_radius=8)
    p1 = f"🟢 {game['my_name']}: {game['my_score']} pts"
    p2 = f"🔵 {game['enemy_name']}: {game['enemy_score']} pts"
    turn = f"⏱️ {300 - game['remaining_moves']}/300"
    screen.blit(font_bold.render(p1, True, (50, 255, 100)), (x + 8, y + 6))
    screen.blit(font_bold.render(p2, True, (60, 180, 255)), (x + 8, y + 24))
    screen.blit(font_small.render(turn, True, (200, 200, 200)), (x + w - 75, y + 6))
    if game["game_over"] and game["winner"]:
        text = font_small.render(f"🏆 {game['winner']}", True, (255, 215, 0))
        screen.blit(text, (x + 8, y + 42))


def _board_geometry(grid, rect):
    x, y, w, h = rect
    rows, cols = len(grid), len(grid[0])
    grid_top = y + 60
    available_w = w - 16
    available_h = h - 68
    cell = max(4, min(available_w // cols, available_h // rows))
    board_w, board_h = cols * cell, rows * cell
    offset_x = x + (w - board_w) // 2
    offset_y = grid_top + (available_h - board_h) // 2
    return cell, offset_x, offset_y


def _draw_cells(pygame, screen, grid, rect, colors):
    cell, ox, oy = _board_geometry(grid, rect)
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            color = colors.get(value, (32, 32, 35))
            cell_rect = (ox + c * cell, oy + r * cell, cell, cell)
            pygame.draw.rect(screen, color, cell_rect)
            if cell >= 12:
                pygame.draw.rect(screen, (45, 45, 50), cell_rect, 1)


def _draw_panel(pygame, screen, game, rect, fonts, food_digits):
    _draw_panel_header(pygame, screen, game, rect, fonts)
    grid = game["grid"]
    if not grid or not grid[0]:
        return
    _draw_cells(pygame, screen, grid, rect, _side_colors(game["my_side"], food_digits))


def _snapshot(state, lock):
    with lock:
        return state["status"], list(state["games"].values())


def _draw_hud(pygame, screen, font, status, count):
    pygame.draw.rect(screen, (15, 15, 18), (0, 0, WINDOW_WIDTH, GLOBAL_HUD_HEIGHT))
    pygame.draw.line(screen, (60, 60, 70), (0, GLOBAL_HUD_HEIGHT), (WINDOW_WIDTH, GLOBAL_HUD_HEIGHT), 2)
    screen.blit(font.render("🐍 Multi-Match Visualizer", True, (255, 255, 255)), (16, 14))
    msg = f"Estado: {status} | Partidas activas: {count}"
    screen.blit(font.render(msg, True, (160, 220, 255)), (WINDOW_WIDTH - 600, 14))


def _panel_rect(index, rows, cols):
    margin = 12
    top = GLOBAL_HUD_HEIGHT + margin
    width = (WINDOW_WIDTH - margin * (cols + 1)) // cols
    height = (WINDOW_HEIGHT - top - margin * rows) // rows
    r_idx, c_idx = divmod(index, cols)
    x = margin + c_idx * (width + margin)
    y = top + r_idx * (height + margin)
    return x, y, width, height


def _draw_games(pygame, screen, games, fonts, food_digits):
    if not games:
        font = fonts[0]
        text = font.render("Esperando partidas activas del servidor...", True, (150, 150, 160))
        screen.blit(text, (WINDOW_WIDTH // 2 - 200, WINDOW_HEIGHT // 2))
        return
    rows, cols = _grid_layout(len(games))
    for index, game in enumerate(games[: rows * cols]):
        _draw_panel(pygame, screen, game, _panel_rect(index, rows, cols), fonts[1:], food_digits)


def _should_quit(pygame):
    return any(event.type == pygame.QUIT for event in pygame.event.get())


def _build_ui(pygame):
    pygame.init()
    pygame.font.init()
    fonts = (
        pygame.font.SysFont("consolas", 16, bold=True),
        pygame.font.SysFont("consolas", 13, bold=True),
        pygame.font.SysFont("consolas", 11),
    )
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("🐍 Code Challenge - Multi-Match Visualizer")
    return screen, fonts, pygame.time.Clock()


def run_visualizer(visual_state, visual_lock, food_digits):
    import pygame
    screen, fonts, clock = _build_ui(pygame)
    while not _should_quit(pygame):
        screen.fill((12, 12, 14))
        status, games = _snapshot(visual_state, visual_lock)
        _draw_hud(pygame, screen, fonts[0], status, len(games))
        _draw_games(pygame, screen, games, fonts, food_digits)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
