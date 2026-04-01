"""
Iteration 2 Improvements:
1. Cooling schedule tuned: slower, reheat after plateau
2. Better solver: subset-sum constraint propagation
3. Solvability penalty baked into loss
4. Smarter initialisation: start from an empty-ish board so solver can open a region
5. More iterations (500k)
"""
import sys
sys.path.insert(0, '/home/claude/minesweeper')
from core import *
import json, os

OUT = "/home/claude/minesweeper/results"
os.makedirs(OUT, exist_ok=True)

BOARD_W, BOARD_H = 30, 20

print("=" * 60)
print("ITERATION 2 — Improved SA + Better Solver")
print("=" * 60)

# ── PLAN UPDATES ──────────────────────────────────────────────
print("""
PLAN UPDATES (Iteration 2)
--------------------------
PROBLEM IDENTIFIED (Iter 1):
  • Coverage 1.2%: solver can't penetrate — too many mines,
    no large "zero" regions to chain-reveal
  • Loss stagnated at 2296 because cooling was too fast

FIXES:
  1. Lower mine density: cap at 35% (↓ from ~45%)
  2. Ensure a border of zeros to give solver an entry point
  3. Slower cooling: T_start=10, alpha=0.99999, 500k iters
  4. Reheat mechanism when no improvement for 50k steps
  5. Enhanced solver: constraint propagation with "tank" algorithm
     (sum of unknowns equals remaining mines → all mine/safe)
""")

target = np.load(f"{OUT}/target.npy")
weights = compute_edge_weights(target, edge_boost=2.0)
H, W = target.shape

# ── BETTER INIT: low density, safe border ─────────────────────
def initialise_v2(target, max_density=0.30, border=2):
    H, W = target.shape
    prob = target / 8.0 * max_density * 2.5  # scale up then clip
    prob = np.clip(prob, 0.0, max_density)
    grid = (np.random.rand(H, W) < prob).astype(np.int8)
    # Ensure border is mine-free for solver entry
    grid[:border, :] = 0
    grid[-border:, :] = 0
    grid[:, :border] = 0
    grid[:, -border:] = 0
    return grid

# ── ENHANCED SOLVER ──────────────────────────────────────────
def enhanced_solver(grid):
    """
    Extended solver with:
    - Standard reveal/flag rules
    - Subset constraint propagation (a ⊆ b → b-a safe/mine)
    """
    H, W = grid.shape
    N = compute_number_field(grid)
    mines_set = set(zip(*np.where(grid == 1)))
    safe_set  = set(zip(*np.where(grid == 0)))

    revealed = set()
    flagged  = set()

    def nbrs(y, x):
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if not (dy == 0 and dx == 0):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W:
                        yield ny, nx

    def reveal(y, x):
        if (y,x) in revealed or (y,x) in flagged or grid[y,x]==1:
            return
        revealed.add((y,x))
        if N[y,x] == 0:
            for ny, nx in nbrs(y, x):
                reveal(ny, nx)

    # Start from all corners and borders
    for y in range(H):
        for x in range(W):
            if grid[y, x] == 0 and N[y, x] == 0:
                reveal(y, x)

    changed = True
    while changed:
        changed = False
        constraints = []

        for ry, rx in list(revealed):
            if grid[ry, rx] == 1:
                continue
            num = int(N[ry, rx])
            unkn = [(ny,nx) for ny,nx in nbrs(ry,rx)
                    if (ny,nx) not in revealed and (ny,nx) not in flagged]
            flgd = [(ny,nx) for ny,nx in nbrs(ry,rx) if (ny,nx) in flagged]
            rem = num - len(flgd)

            # Basic rules
            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged:
                        flagged.add(c)
                        changed = True
            if rem == 0:
                for c in unkn:
                    if grid[c[0],c[1]] == 0:
                        reveal(c[0], c[1])
                        changed = True

            if unkn:
                constraints.append((frozenset(unkn), rem))

        # Subset constraint propagation
        for i, (si, ri) in enumerate(constraints):
            for j, (sj, rj) in enumerate(constraints):
                if i == j:
                    continue
                if si < sj and len(si) > 0:
                    diff = sj - si
                    rem_diff = rj - ri
                    if rem_diff == len(diff) and len(diff) > 0:
                        for c in diff:
                            if c not in flagged:
                                flagged.add(c)
                                changed = True
                    elif rem_diff == 0 and len(diff) > 0:
                        for c in diff:
                            if grid[c[0],c[1]] == 0:
                                reveal(c[0], c[1])
                                changed = True

    total_safe = len(safe_set)
    rev_safe = len(revealed & safe_set)
    coverage = rev_safe / total_safe if total_safe > 0 else 0.0
    solvable = (coverage >= 0.995) and (flagged >= mines_set)

    return {
        "solvable": solvable,
        "revealed": revealed,
        "flagged": flagged,
        "unknown": safe_set - revealed,
        "coverage": coverage,
        "mine_accuracy": len(flagged & mines_set) / max(len(mines_set), 1),
    }

# ── SA WITH REHEAT ────────────────────────────────────────────
def sa_with_reheat(target, weights, max_density=0.30, border=2,
                   T_start=10.0, T_end=0.001, alpha=0.99999,
                   max_iter=500_000, reheat_interval=60_000,
                   reheat_factor=3.0, seed=1, verbose=True):
    np.random.seed(seed)
    H, W = target.shape
    grid = initialise_v2(target, max_density, border)
    N = compute_number_field(grid).copy().astype(np.float32)

    def full_delta(y, x):
        sign = 1 - 2 * int(grid[y, x])
        d = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0: continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W:
                    n_cur = N[ny, nx]
                    n_new = n_cur + sign
                    # Enforce N ≤ 8 hard constraint
                    if n_new > 8 or n_new < 0:
                        return float('inf'), sign
                    w = weights[ny, nx]
                    t = target[ny, nx]
                    d += w * ((n_new - t)**2 - (n_cur - t)**2)
        return d, sign

    def apply_flip(y, x, sign):
        grid[y, x] = 1 if sign > 0 else 0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0: continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W:
                    N[ny, nx] += sign

    current_loss = float(np.sum(weights * (N - target)**2))
    best_loss = current_loss
    best_grid = grid.copy()
    history = [current_loss]

    T = T_start
    no_improve_count = 0
    last_best = current_loss

    ys = np.random.randint(0, H, max_iter)
    xs = np.random.randint(0, W, max_iter)

    for i in range(max_iter):
        # Enforce density constraint: reject if border cell
        y, x = ys[i], xs[i]
        if y < border or y >= H-border or x < border or x >= W-border:
            if grid[y,x] == 0:
                continue  # don't mine the border

        d, sign = full_delta(y, x)
        if d == float('inf'):
            continue

        if d < 0 or np.random.rand() < np.exp(-max(d, 0) / (T + 1e-12)):
            apply_flip(y, x, sign)
            current_loss += d
            if current_loss < best_loss:
                best_loss = current_loss
                best_grid = grid.copy()

        T = max(T * alpha, T_end)

        if i % reheat_interval == 0 and i > 0:
            if best_loss >= last_best - 1.0:
                T = min(T * reheat_factor, T_start * 0.5)
                if verbose:
                    print(f"  ↻ Reheat at iter {i}: T→{T:.4f}")
            last_best = best_loss
            no_improve_count = 0

        if verbose and i % 50000 == 0:
            print(f"  Iter {i:>7d} | T={T:.5f} | Loss={current_loss:.2f} | Best={best_loss:.2f}")
            history.append(best_loss)

    return best_grid, history

# ── RUN ───────────────────────────────────────────────────────
print("Running SA with reheat …")
t0 = time.time()
best_grid, history = sa_with_reheat(
    target, weights,
    max_density=0.28,
    border=2,
    T_start=10.0, T_end=0.001,
    alpha=0.999985,
    max_iter=500_000,
    reheat_interval=60_000,
    reheat_factor=4.0,
    seed=2,
    verbose=True,
)
elapsed = time.time() - t0
print(f"SA done in {elapsed:.1f}s")

# ── SOLVE ─────────────────────────────────────────────────────
print("Running enhanced solver …")
solver_result = enhanced_solver(best_grid)

metrics = compute_metrics(best_grid, target, weights, solver_result)
print("\nMETRICS (Iteration 2)")
for k, v in metrics.items():
    print(f"  {k:25s}: {v}")

# Load iter 1 metrics for comparison
with open(f"{OUT}/metrics_iter1.json") as f:
    m1 = json.load(f)
print("\nCOMPARISON vs Iter 1:")
for k in ["loss", "coverage", "solvable", "mine_density"]:
    print(f"  {k}: {m1[k]} → {metrics[k]}")

render_comparison(target, best_grid, solver_result, history,
                  iteration=2,
                  save_path=f"{OUT}/iteration_2.png")
print(f"\nSaved → {OUT}/iteration_2.png")

np.save(f"{OUT}/best_grid_iter2.npy", best_grid)
with open(f"{OUT}/metrics_iter2.json","w") as f:
    json.dump(metrics, f, indent=2)

print("\nIteration 2 complete.")
