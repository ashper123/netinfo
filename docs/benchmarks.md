# Performance & Benchmarks

`netinfo` is designed for ultra-low latency execution across large networks.

## Subnet Discovery Benchmark (/24 Subnet — 254 Hosts)

| Execution Method | Execution Time | Speedup |
|---|---|---|
| Sequential Scan (`netinfo v1.0`) | ~240.0 seconds | 1× Baseline |
| **Parallel Sweep (`netinfo v2.0` — 64 Workers)** | **~2.1 seconds** | **~114× Faster** |

## Subprocess Overhead Reduction (Windows)

By caching the `ipconfig /all` command output string for the duration of a report run, `netinfo` executes `ipconfig /all` exactly **once** instead of 3 times, saving **200–400 ms** per run on Windows systems.
