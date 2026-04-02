from __future__ import annotations

from .core import get_neighbor_table


def forcing_potential_score(
    N_cur,
    edits: list[tuple[int, int, int]],
    revealed: set[tuple[int, int]],
    flagged: set[tuple[int, int]],
    H: int,
    W: int,
    frontier_radius: int = 3,
) -> int:
    """
    Estimate local forcing potential after candidate mine edits.

    edits: list[(y, x, mine_delta)] where mine_delta is +1 for add, -1 for remove.
    Returns count(forced-safe cells) + count(forced-flag cells) in local frontier.
    """
    neighbors = get_neighbor_table(H, W)

    delta_map: dict[tuple[int, int], int] = {}
    for y, x, mine_delta in edits:
        for ny, nx in neighbors[y][x]:
            delta_map[(ny, nx)] = delta_map.get((ny, nx), 0) + mine_delta

    frontier = set()
    for y, x, _ in edits:
        for dy in range(-frontier_radius, frontier_radius + 1):
            for dx in range(-frontier_radius, frontier_radius + 1):
                ry, rx = y + dy, x + dx
                if 0 <= ry < H and 0 <= rx < W and (ry, rx) in revealed:
                    frontier.add((ry, rx))

    if not frontier:
        return 0

    forced_safe = set()
    forced_flag = set()
    for ry, rx in sorted(frontier):
        num_new = int(N_cur[ry, rx]) + delta_map.get((ry, rx), 0)
        if num_new < 0 or num_new > 8:
            return -1

        unknown_nbrs = []
        flagged_count = 0
        for ny, nx in neighbors[ry][rx]:
            if (ny, nx) in flagged:
                flagged_count += 1
            elif (ny, nx) not in revealed:
                unknown_nbrs.append((ny, nx))

        if not unknown_nbrs:
            continue

        rem = num_new - flagged_count
        if rem == 0:
            forced_safe.update(unknown_nbrs)
        elif rem == len(unknown_nbrs):
            forced_flag.update(unknown_nbrs)

    return len(forced_safe) + len(forced_flag)
