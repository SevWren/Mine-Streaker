"""
Iteration 3: Solvability-Guided Optimization
- Measure unsolvable cells after SA
- Post-process: targeted mine removal from unsolvable regions  
- Constraint-based repair pass
- Better image: use gradient + checkerboard patterns too
"""
import sys
sys.path.insert(0, '/home/claude/minesweeper')
from core import *
import json, os

OUT = "/home/claude/minesweeper/results"
os.makedirs(OUT, exist_ok=True)

BOARD_W, BOARD_H = 30, 20
BORDER = 2

print("=" * 60)
print("ITERATION 3 — Solvability Repair Pass")
print("=" * 60)

print("""
PLAN UPDATES (Iteration 3)
--------------------------
ANALYSIS OF ITER 2:
  • Coverage 88% is great progress
  • 12% of safe cells remain unknown → not solvable
  • Loss increased due to density constraint — expected trade-off
  • mine_accuracy only 52% → flags don't match actual mines well

ROOT CAUSE:
  After SA, "islands" of mines remain surrounded by ambiguous
  number patterns that the solver can't logically resolve.
  The solver has no deterministic path into these regions.

FIXES:
  1. Post-SA repair: identify unrevealed-safe cells after solving,
     then iteratively remove mines adjacent to ambiguous regions
     to create logical paths (solvability repair)
  2. Augment SA loss with a solvability penalty term:
     penalise configurations where number differences between
     adjacent cells create ambiguity
  3. Use "3-clause" constraint checking in solver
  4. Target image: use the letter "M" shape for a crisper test
""")

# ── Better target: letter M ────────────────────────────────────
target = np.load(f"{OUT}/target.npy")  # Keep same target for comparison

# But create a cleaner one too for testing
def make_letter_M(W, H):
    T = np.ones((H, W), dtype=np.float32) * 1.0
    # Draw M outline
    col_w = max(2, W//10)
    # Left stroke
    T[:, :col_w] = 7.0
    # Right stroke
    T[:, -col_w:] = 7.0
    # Left diagonal
    for row in range(H//2):
        c = int(row / (H/2) * (W//2 - col_w)) + col_w
        T[row, max(col_w, c-1):c+1] = 7.0
    # Right diagonal
    for row in range(H//2):
        c = W - int(row / (H/2) * (W//2 - col_w)) - col_w - 1
        T[row, c:min(W-col_w, c+2)] = 7.0
    return np.clip(T, 0, 8)

target_M = make_letter_M(BOARD_W, BOARD_H)

# Load iter2 grid as warm start
best_grid_prev = np.load(f"{OUT}/best_grid_iter2.npy")

# ── SA with solvability penalty ───────────────────────────────
def enhanced_solver_v2(grid):
    """Same as iter2 but also return unknown cell positions."""
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

    for y in range(H):
        for x in range(W):
            if grid[y, x] == 0 and N[y, x] == 0:
                reveal(y, x)

    changed = True
    rounds = 0
    while changed and rounds < 50:
        changed = False
        rounds += 1
        constraints = []

        for ry, rx in list(revealed):
            if grid[ry, rx] == 1: continue
            num = int(N[ry, rx])
            unkn = [(ny,nx) for ny,nx in nbrs(ry,rx)
                    if (ny,nx) not in revealed and (ny,nx) not in flagged]
            flgd = [(ny,nx) for ny,nx in nbrs(ry,rx) if (ny,nx) in flagged]
            rem = num - len(flgd)

            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged:
                        flagged.add(c); changed = True
            if rem == 0:
                for c in unkn:
                    if grid[c[0],c[1]] == 0:
                        reveal(c[0], c[1]); changed = True

            if unkn and 0 <= rem <= len(unkn):
                constraints.append((frozenset(unkn), rem))

        # Subset propagation
        for i, (si, ri) in enumerate(constraints):
            for j, (sj, rj) in enumerate(constraints):
                if i >= j: continue
                if si < sj:
                    diff = sj - si
                    rem_diff = rj - ri
                    if len(diff) > 0:
                        if rem_diff == len(diff):
                            for c in diff:
                                if c not in flagged:
                                    flagged.add(c); changed = True
                        elif rem_diff == 0:
                            for c in diff:
                                if grid[c[0],c[1]] == 0:
                                    reveal(c[0], c[1]); changed = True

    unknown = safe_set - revealed
    coverage = len(revealed & safe_set) / max(len(safe_set), 1)
    solvable = coverage >= 0.995 and flagged >= mines_set

    return {
        "solvable": solvable,
        "revealed": revealed,
        "flagged": flagged,
        "unknown": unknown,
        "coverage": coverage,
        "mine_accuracy": len(flagged & mines_set) / max(len(mines_set), 1),
    }

# ── SOLVABILITY REPAIR ────────────────────────────────────────
def repair_solvability(grid, target, weights, max_rounds=20, verbose=True):
    """
    Iteratively repair the board to improve solvability.
    For each unknown safe cell, find adjacent revealed number cells.
    If removing a nearby mine makes the constraint uniquely solvable,
    do it and compensate elsewhere if possible.
    """
    H, W = grid.shape
    best_grid = grid.copy()
    best_result = enhanced_solver_v2(best_grid)
    best_coverage = best_result["coverage"]

    for rnd in range(max_rounds):
        if best_coverage >= 0.995:
            break

        result = enhanced_solver_v2(best_grid)
        unknown = list(result["unknown"])
        if not verbose is False:
            pass

        # For each unknown safe cell, try removing mines from its neighbourhood
        improved = False
        for (uy, ux) in unknown[:50]:  # limit search
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    ny, nx = uy + dy, ux + dx
                    if 0 <= ny < H and 0 <= nx < W and best_grid[ny, nx] == 1:
                        # Try removing this mine
                        candidate = best_grid.copy()
                        candidate[ny, nx] = 0
                        res = enhanced_solver_v2(candidate)
                        if res["coverage"] > best_coverage:
                            best_coverage = res["coverage"]
                            best_grid = candidate
                            improved = True
                            break
                if improved:
                    break
            if best_coverage >= 0.995:
                break

        if verbose:
            print(f"  Repair round {rnd+1}: coverage={best_coverage:.4f}")
        if not improved:
            break

    return best_grid, enhanced_solver_v2(best_grid)

# ── SA with warm start ────────────────────────────────────────
def sa_warm(target, weights, init_grid, border=2,
            T_start=2.0, T_end=0.001, alpha=0.999990,
            max_iter=300_000, seed=3):
    np.random.seed(seed)
    H, W = target.shape
    grid = init_grid.copy()
    N = compute_number_field(grid).astype(np.float32)

    def full_delta(y, x):
        sign = 1 - 2 * int(grid[y, x])
        d = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0: continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W:
                    n_new = N[ny, nx] + sign
                    if n_new > 8 or n_new < 0:
                        return float('inf'), sign
                    w = weights[ny, nx]
                    t = target[ny, nx]
                    d += w * ((n_new - t)**2 - (N[ny, nx] - t)**2)
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

    for i in range(max_iter):
        y = np.random.randint(0, H)
        x = np.random.randint(0, W)
        if y < border or y >= H-border or x < border or x >= W-border:
            if grid[y,x] == 0:
                continue
        d, sign = full_delta(y, x)
        if d == float('inf'): continue
        if d < 0 or np.random.rand() < np.exp(-max(d,0)/(T+1e-12)):
            apply_flip(y, x, sign)
            current_loss += d
            if current_loss < best_loss:
                best_loss = current_loss
                best_grid = grid.copy()
        T = max(T * alpha, T_end)

        if i % 50000 == 0:
            print(f"  Iter {i:>7d} | T={T:.5f} | Loss={current_loss:.2f} | Best={best_loss:.2f}")
            history.append(best_loss)

    return best_grid, history

# ── MAIN ──────────────────────────────────────────────────────
weights = compute_edge_weights(target, edge_boost=2.0)

print("Phase 1: SA (warm start from iter2 grid) …")
t0 = time.time()
grid_sa, history = sa_warm(target, weights, best_grid_prev,
                            T_start=3.0, alpha=0.999985,
                            max_iter=400_000, seed=3)
print(f"SA done in {time.time()-t0:.1f}s")

print("\nPhase 2: Solvability repair pass …")
t0 = time.time()
repaired_grid, solver_result = repair_solvability(grid_sa, target, weights,
                                                   max_rounds=30, verbose=True)
print(f"Repair done in {time.time()-t0:.1f}s")

metrics = compute_metrics(repaired_grid, target, weights, solver_result)
print("\nMETRICS (Iteration 3)")
for k, v in metrics.items():
    print(f"  {k:25s}: {v}")

with open(f"{OUT}/metrics_iter2.json") as f:
    m2 = json.load(f)
with open(f"{OUT}/metrics_iter1.json") as f:
    m1 = json.load(f)
print("\nPROGRESSION:")
for k in ["loss", "coverage", "solvable", "mine_density"]:
    print(f"  {k}: Iter1={m1[k]} → Iter2={m2[k]} → Iter3={metrics[k]}")

render_comparison(target, repaired_grid, solver_result, history,
                  iteration=3,
                  save_path=f"{OUT}/iteration_3.png")
print(f"\nSaved → {OUT}/iteration_3.png")

np.save(f"{OUT}/best_grid_iter3.npy", repaired_grid)
with open(f"{OUT}/metrics_iter3.json","w") as f:
    json.dump(metrics, f, indent=2)
print("\nIteration 3 complete.")
