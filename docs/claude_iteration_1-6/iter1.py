"""
Iteration 1 Runner
"""
import sys
sys.path.insert(0, '/home/claude/minesweeper')
from core import *
import json, os

OUT = "/home/claude/minesweeper/results"
os.makedirs(OUT, exist_ok=True)

BOARD_W, BOARD_H = 30, 20   # manageable for iteration 1

print("=" * 60)
print("ITERATION 1 — Base Simulated Annealing")
print("=" * 60)

# ── PLAN ──────────────────────────────────────────────────────
print("""
PLAN
----
• Pattern: synthetic smiley-face (avoids I/O dependency)
• Board:   30×20 cells
• Init:    probabilistic seeding from target brightness
• Optim:   simulated annealing, geometric cooling, 200k iters
• Weights: edge-boosted (3×)
• Solver:  deterministic CSP (reveal→flag→reveal loop)
• Metrics: loss, density, coverage, solvability
""")

# ── GENERATE TARGET ────────────────────────────────────────────
target = generate_synthetic_target(BOARD_W, BOARD_H, "face")
weights = compute_edge_weights(target, edge_boost=3.0)

print(f"Target shape: {target.shape}  range:[{target.min():.2f},{target.max():.2f}]")

# ── OPTIMISE ───────────────────────────────────────────────────
print("\nRunning simulated annealing …")
t0 = time.time()
best_grid, history = simulated_annealing(
    target, weights,
    T_start=8.0, T_end=0.01,
    max_iter=200_000,
    alpha=0.99993,
    seed=0,
    verbose=True,
)
elapsed = time.time() - t0
print(f"SA done in {elapsed:.1f}s")

# ── SOLVER ────────────────────────────────────────────────────
print("\nRunning solver …")
solver_result = minesweeper_solver(best_grid)

# ── METRICS ───────────────────────────────────────────────────
metrics = compute_metrics(best_grid, target, weights, solver_result)
print("\nMETRICS (Iteration 1)")
for k, v in metrics.items():
    print(f"  {k:25s}: {v}")

# ── RENDER ────────────────────────────────────────────────────
render_comparison(target, best_grid, solver_result, history,
                  iteration=1,
                  save_path=f"{OUT}/iteration_1.png")
print(f"\nSaved → {OUT}/iteration_1.png")

# ── SAVE STATE ────────────────────────────────────────────────
np.save(f"{OUT}/best_grid_iter1.npy", best_grid)
np.save(f"{OUT}/target.npy", target)
with open(f"{OUT}/metrics_iter1.json", "w") as f:
    json.dump(metrics, f, indent=2)

print("\nIteration 1 complete.")
