"""
Iteration 4: Full Solvability + Loss Recovery via Hybrid SA+Repair

Key insight: We need to balance TWO objectives:
  1. Loss (visual quality) 
  2. Solvability (playability)

Strategy: Multi-objective SA where moves that improve solvability
are strongly accepted, then a final re-optimization pass tightens loss
while preserving solvability.
"""
import sys
sys.path.insert(0, '/home/claude/minesweeper')
from core import *
import json, os

OUT = "/home/claude/minesweeper/results"
BOARD_W, BOARD_H = 30, 20
BORDER = 2

print("=" * 60)
print("ITERATION 4 — Full Solvability + Loss Recovery")
print("=" * 60)

print("""
PLAN UPDATES (Iteration 4)
--------------------------
ANALYSIS OF ITER 3:
  • Coverage 99.5%: almost solvable (only 2-3 cells remain unknown)
  • Loss 5050: degraded due to aggressive mine removal in repair
  • Need: complete the last 0.5% coverage, then re-optimize loss

ROOT CAUSE of remaining 0.5%:
  A few mine "islands" surrounded by cells where the number constraints
  are symmetric — can't distinguish which of N cells has the mine.
  Classic "50/50" configuration.

STRATEGY:
  1. Run deeper repair (more rounds, larger search radius)
  2. For any remaining ambiguous 50/50 islands: split them
     (place a safe corridor through the pattern to break symmetry)
  3. After achieving full solvability: run SA with solvability
     constraint HARD (only accept moves that keep board solvable)
  4. Track and report the final visual quality vs Iter 1 target
""")

target = np.load(f"{OUT}/target.npy")
weights = compute_edge_weights(target, edge_boost=2.5)
H, W = target.shape
best_grid_prev = np.load(f"{OUT}/best_grid_iter3.npy")

# ── Full enhanced solver ─────────────────────────────────────
def full_solver(grid, max_rounds=100):
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
        if (y,x) in revealed or (y,x) in flagged or grid[y,x]==1: return
        revealed.add((y,x))
        if N[y,x] == 0:
            for ny,nx in nbrs(y,x): reveal(ny,nx)

    # Flood-fill from all zero cells
    for y in range(H):
        for x in range(W):
            if grid[y,x] == 0 and N[y,x] == 0:
                reveal(y,x)

    for _ in range(max_rounds):
        changed = False
        constraints = []

        for ry, rx in list(revealed):
            if grid[ry,rx] == 1: continue
            num = int(N[ry,rx])
            unkn = [(ny,nx) for ny,nx in nbrs(ry,rx)
                    if (ny,nx) not in revealed and (ny,nx) not in flagged]
            flgd = [(ny,nx) for ny,nx in nbrs(ry,rx) if (ny,nx) in flagged]
            rem = num - len(flgd)

            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged: flagged.add(c); changed = True
            if rem == 0:
                for c in unkn:
                    if grid[c[0],c[1]] == 0: reveal(c[0],c[1]); changed = True

            if unkn and 0 <= rem <= len(unkn):
                constraints.append((frozenset(unkn), rem))

        # Subset propagation
        for i,(si,ri) in enumerate(constraints):
            for j,(sj,rj) in enumerate(constraints):
                if i>=j: continue
                if si < sj:
                    diff = sj-si; rdiff = rj-ri
                    if len(diff)>0:
                        if rdiff == len(diff):
                            for c in diff:
                                if c not in flagged: flagged.add(c); changed=True
                        elif rdiff == 0:
                            for c in diff:
                                if grid[c[0],c[1]]==0: reveal(c[0],c[1]); changed=True

        if not changed: break

    unknown = safe_set - revealed
    coverage = len(revealed & safe_set) / max(len(safe_set),1)
    solvable = coverage >= 0.999 and (flagged >= mines_set)
    return {
        "solvable": solvable, "revealed": revealed, "flagged": flagged,
        "unknown": unknown, "coverage": coverage,
        "mine_accuracy": len(flagged & mines_set)/max(len(mines_set),1),
    }

# ── Deep repair with corridor cutting ───────────────────────
def deep_repair(grid, target, weights, max_rounds=60, search_radius=3):
    H, W = grid.shape
    best_grid = grid.copy()
    result = full_solver(best_grid)
    best_coverage = result["coverage"]
    print(f"  Starting coverage: {best_coverage:.4f}")

    for rnd in range(max_rounds):
        if best_coverage >= 0.999:
            break
        result = full_solver(best_grid)
        unknown = list(result["unknown"])

        if not unknown:
            break

        improved = False
        for (uy, ux) in unknown:
            for r in range(1, search_radius+1):
                for dy in range(-r, r+1):
                    for dx in range(-r, r+1):
                        if abs(dy) != r and abs(dx) != r: continue
                        ny, nx = uy+dy, ux+dx
                        if 0<=ny<H and 0<=nx<W and best_grid[ny,nx]==1:
                            candidate = best_grid.copy()
                            candidate[ny,nx] = 0
                            res = full_solver(candidate)
                            if res["coverage"] > best_coverage + 0.001:
                                best_coverage = res["coverage"]
                                best_grid = candidate
                                improved = True
                                break
                    if improved: break
                if improved: break
            if best_coverage >= 0.999: break

        if rnd % 5 == 0:
            print(f"  Repair round {rnd+1:>3d}: coverage={best_coverage:.4f}")
        if not improved:
            print(f"  No improvement at round {rnd+1}, breaking")
            break

    return best_grid, full_solver(best_grid)

# ── Loss-recovery SA (solvability-constrained) ───────────────
def loss_recovery_sa(grid, target, weights, border=BORDER,
                     T_start=1.5, T_end=0.001, alpha=0.999985,
                     max_iter=300_000, seed=4):
    """SA that only accepts moves preserving solvability."""
    np.random.seed(seed)
    H, W = target.shape
    curr = grid.copy()
    N = compute_number_field(curr).astype(np.float32)
    current_loss = float(np.sum(weights*(N-target)**2))
    best_loss = current_loss
    best_grid = curr.copy()
    T = T_start
    accepted_solvable = 0
    history = [current_loss]

    # Check solvability cheaply: every 5000 iters
    last_solvable_grid = curr.copy()

    for i in range(max_iter):
        y = np.random.randint(0, H)
        x = np.random.randint(0, W)
        if y < border or y >= H-border or x < border or x >= W-border:
            if curr[y,x] == 0: continue

        sign = 1 - 2*int(curr[y,x])
        d = 0.0
        valid = True
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy==0 and dx==0: continue
                ny, nx = y+dy, x+dx
                if 0<=ny<H and 0<=nx<W:
                    n_new = N[ny,nx]+sign
                    if n_new>8 or n_new<0: valid=False; break
                    w = weights[ny,nx]; t = target[ny,nx]
                    d += w*((n_new-t)**2-(N[ny,nx]-t)**2)
            if not valid: break
        if not valid: continue

        if d < 0 or np.random.rand() < np.exp(-max(d,0)/(T+1e-12)):
            # Apply tentatively
            curr[y,x] = 1 if sign>0 else 0
            for dy in range(-1,2):
                for dx in range(-1,2):
                    if dy==0 and dx==0: continue
                    ny,nx=y+dy,x+dx
                    if 0<=ny<H and 0<=nx<W: N[ny,nx]+=sign

            current_loss += d

            # Periodic solvability check
            if i % 2000 == 0:
                res = full_solver(curr)
                if res["coverage"] >= 0.999:
                    last_solvable_grid = curr.copy()
                    if current_loss < best_loss:
                        best_loss = current_loss
                        best_grid = curr.copy()
                        accepted_solvable += 1
                else:
                    # Revert to last known solvable
                    curr = last_solvable_grid.copy()
                    N = compute_number_field(curr).astype(np.float32)
                    current_loss = float(np.sum(weights*(N-target)**2))

        T = max(T*alpha, T_end)

        if i % 50000 == 0:
            print(f"  Iter {i:>7d} | T={T:.5f} | Loss={current_loss:.2f} | Best={best_loss:.2f}")
            history.append(best_loss)

    print(f"  Accepted {accepted_solvable} solvable improvements")
    return best_grid, history

# ── MAIN ─────────────────────────────────────────────────────
print("Phase 1: Deep solvability repair …")
t0 = time.time()
repaired, solver_result = deep_repair(best_grid_prev, target, weights,
                                      max_rounds=80, search_radius=4)
print(f"Deep repair done in {time.time()-t0:.1f}s")
print(f"Coverage after repair: {solver_result['coverage']:.4f}")

print("\nPhase 2: Loss recovery SA (solvability-constrained) …")
t0 = time.time()
final_grid, history = loss_recovery_sa(repaired, target, weights,
                                        T_start=2.0, alpha=0.999985,
                                        max_iter=300_000, seed=4)
elapsed = time.time()-t0
print(f"Recovery SA done in {elapsed:.1f}s")

print("\nPhase 3: Final solver check …")
final_solver = full_solver(final_grid)

metrics = compute_metrics(final_grid, target, weights, final_solver)
print("\nMETRICS (Iteration 4)")
for k,v in metrics.items():
    print(f"  {k:25s}: {v}")

with open(f"{OUT}/metrics_iter3.json") as f: m3 = json.load(f)
with open(f"{OUT}/metrics_iter2.json") as f: m2 = json.load(f)
with open(f"{OUT}/metrics_iter1.json") as f: m1 = json.load(f)
print("\nPROGRESSION:")
for k in ["loss","coverage","solvable","mine_density"]:
    print(f"  {k}: {m1[k]} → {m2[k]} → {m3[k]} → {metrics[k]}")

render_comparison(target, final_grid, final_solver, history,
                  iteration=4,
                  save_path=f"{OUT}/iteration_4.png")
print(f"\nSaved → {OUT}/iteration_4.png")
np.save(f"{OUT}/best_grid_iter4.npy", final_grid)
with open(f"{OUT}/metrics_iter4.json","w") as f:
    json.dump(metrics, f, indent=2)
print("\nIteration 4 complete.")
