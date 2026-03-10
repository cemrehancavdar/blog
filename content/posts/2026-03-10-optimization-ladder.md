---
title: "The Optimization Ladder"
date: 2026-03-10T20:00:00
type: post
tags: [python, performance, benchmark, cython, rust, numba, numpy, mypyc, mojo, codon, taichi, graalpy, pypy]
draft: false
unlisted: false
subtitle: "every way to make Python fast, benchmarked"
description: "Python loses every public benchmark by 21-875x. I took the exact problems people use to dunk on Python and climbed every rung of the optimization ladder -- from CPython version upgrades to Rust. Real numbers, real code, real effort costs."
---

Every year, someone posts a benchmark showing Python is 100x slower than C. The same argument plays out: one side says "benchmarks don't matter, real apps are I/O bound," the other says "just use a real language." Both are wrong.

I took two of the most-cited <a href="https://benchmarksgame-team.pages.debian.net/benchmarksgame/" target="_blank">Benchmarks Game</a> problems -- **n-body** and **spectral-norm** -- reproduced them on my machine, and ran every optimization tool I could find. Then I added a third benchmark -- a JSON event pipeline -- to test something closer to real-world code.

Same problems, same Apple M4 Pro, real numbers. This is one developer's journey up the ladder -- not a definitive ranking. A dedicated expert could squeeze more out of any of these tools. The full code is at <a href="https://github.com/cemrehancavdar/faster-python-bench" target="_blank">faster-python-bench</a>.

Here's the starting point -- CPython 3.13 on the official Benchmarks Game run:

<div class="bench-table">

| Benchmark | C gcc | CPython 3.13 | Ratio |
|---|---|---|---|
| n-body (50M) | 2.1s | 372s | **177x** |
| spectral-norm (5500) | 0.4s | 350s | **875x** |
| fannkuch-redux (12) | 2.1s | 311s | **145x** |
| mandelbrot (16000) | 1.3s | 183s | **142x** |
| binary-trees (21) | 1.6s | 33s | **21x** |

</div>

The question isn't whether Python is slow at computation. It is. The question is how much effort each fix costs and how far it gets you. That's the ladder.

---

## Why Python Is Slow

The usual suspects are the GIL, interpretation, and dynamic typing. All three matter, but none of them is the real story. The real story is that Python is designed to be *maximally dynamic* -- you can monkey-patch methods at runtime, replace builtins, change a class's inheritance chain while instances exist -- and that design makes it **fundamentally hard to optimize**.

A C compiler sees `a + b` between two integers and emits one CPU instruction. The Python VM sees `a + b` and has to ask: what is `a`? What is `b`? Does `a.__add__` exist? Has it been replaced since the last call? Is `a` actually a subclass of `int` that overrides `__add__`? Every operation goes through this dispatch because the language *guarantees* you can change anything at any time.

The object overhead is where this shows up concretely. In C, an integer is 4 bytes on the stack. In Python:

```
C int:        [    4 bytes    ]

Python int:   [ ob_refcnt  8B ]    reference count
              [ ob_type    8B ]    pointer to type object
              [ ob_size    8B ]    number of digits
              [ ob_digit   4B ]    the actual value
              ─────────────────
              = 28 bytes minimum
```

(Simplified -- CPython 3.12+ replaced `ob_size` with `lv_tag` in a restructured int layout. Total is still 28 bytes. See <a href="https://github.com/python/cpython/blob/main/Include/cpython/longintrepr.h" target="_blank">longintrepr.h</a>.)

4 bytes of number, 24 bytes of machinery to support dynamism. `a + b` means: dereference two heap pointers, look up type slots, dispatch to `int.__add__`, allocate a new `PyObject` for the result (unless it hits the small-integer cache), update reference counts. CPython 3.11+ mitigates this with <a href="https://docs.python.org/3/whatsnew/3.11.html#faster-cpython" target="_blank">adaptive specialization</a> -- hot bytecodes like `BINARY_OP_ADD_INT` skip the dispatch for known types -- but the overhead is still there for the general case. One number isn't slow. Millions in a loop are.

The GIL (Global Interpreter Lock) gets blamed a lot, but it has **no impact on single-threaded performance** -- it only matters when multiple CPU-bound threads compete for the interpreter. For the benchmarks in this post, the GIL is irrelevant. CPython 3.13 shipped experimental free-threaded mode (`--disable-gil`) -- still experimental in 3.14 -- but as we'll see, it actually makes single-threaded code *slower* because removing the GIL adds overhead to every reference count operation.

The interpretation overhead is real but is being actively addressed. CPython 3.11's <a href="https://docs.python.org/3/whatsnew/3.11.html#faster-cpython" target="_blank">Faster CPython</a> project added adaptive specialization -- the VM detects "hot" bytecodes and replaces them with type-specialized versions, skipping some of the dispatch. It helped (~1.4x). CPython 3.13 went further with an experimental <a href="https://docs.python.org/3/whatsnew/3.13.html#an-experimental-jit-compiler" target="_blank">copy-and-patch JIT compiler</a> -- a lightweight JIT that stitches together pre-compiled machine code templates instead of generating code from scratch. It's not a full optimizing JIT like V8's TurboFan or a tracing JIT like PyPy's; it's designed to be small and fast to start, avoiding the heavyweight JIT startup cost that has historically kept CPython from going this route. Early results are modest (single-digit percent improvements), but the infrastructure is now in place for more aggressive optimizations in future releases. JavaScript's V8 achieves much better JIT results, but V8 also had a large dedicated team and a single-threaded JavaScript execution model that makes speculative optimization easier. (For more on the "why doesn't CPython JIT" question, see Anthony Shaw's <a href="https://tonybaloney.github.io/posts/why-is-python-so-slow.html#so-why-doesnt-cpython-use-a-jit" target="_blank">"Why is Python so slow?"</a>.)

So the picture is: **Python is slow because its dynamic design requires runtime dispatch on every operation.** The GIL, the interpreter, the object model -- these are all consequences of that design choice. Each rung of the ladder removes some of this dispatch. The higher you climb, the more you bypass -- and the more effort it costs.

---

## Rung 0: Upgrade CPython

**Cost: changing your base image. Reward: up to 1.4x.**

<div class="bench-table">

| Version | N-body | vs 3.14 | Spectral-norm | vs 3.14 |
|---|---|---|---|---|
| CPython 3.10 | 1,663ms | 0.75x | 16,826ms | 0.83x |
| CPython 3.11 | 1,200ms | 1.04x | 13,430ms | 1.05x |
| CPython 3.13 | 1,134ms | 1.10x | 13,637ms | 1.03x |
| CPython 3.14 | 1,242ms | 1.0x | 14,046ms | 1.0x |
| CPython 3.14t (free-threaded) | 1,513ms | 0.82x | 14,551ms | 0.97x |

</div>

The story is **3.10 to 3.11**: a 1.39x speedup on n-body, for free. That's the <a href="https://docs.python.org/3/whatsnew/3.11.html#faster-cpython" target="_blank">Faster CPython</a> project -- adaptive specialization of bytecodes, inline caching, zero-cost exceptions. 3.13 squeezed out a bit more. 3.14 gave some of it back -- a minor regression on these benchmarks.

Free-threaded Python (3.14t) is **slower** on single-threaded code. The GIL removal adds overhead to every reference count operation. Worth it only if you have genuinely parallel CPU-bound threads. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cpython-versions.md" target="_blank">Full version comparison</a>)

This rung costs nothing. If you're still on 3.10, upgrade.

---

## Rung 1: Alternative Runtimes (PyPy, GraalPy)

**Cost: switching interpreters. Reward: 6-66x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.14 | 1,242ms | 14,046ms |
| GraalPy | 211ms (**5.9x**) | 212ms (**66x**) |
| PyPy | 98ms (**13x**) | 1,065ms (**13x**) |

</div>

Both are JIT-compiled runtimes that generate native machine code from your unmodified Python. Zero code changes. Just a different interpreter.

PyPy uses a tracing JIT -- it records hot loops and compiles them. GraalPy runs on GraalVM's Truffle framework with a method-based JIT. PyPy wins on n-body (13x vs 5.9x), but GraalPy dominates spectral-norm (66x vs 13x) -- the matrix-heavy inner loop plays to GraalVM's strengths. GraalPy also offers Java interop and is actively developed by Oracle.

The catch: ecosystem compatibility. Both support major packages, but C extensions run through compatibility layers that can be slower than on CPython. GraalPy is on Python 3.12 (no 3.14 yet) and has slow startup -- it's JVM-based, so the JIT needs warmup before reaching peak performance. For pure Python code with long-running hot loops -- these are free speed.

---

## Rung 2: Mypyc

**Cost: type annotations you probably already have. Reward: 2.4-14x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.14 | 1,242ms | 14,046ms |
| Mypyc | 518ms (**2.4x**) | 990ms (**14x**) |

</div>

Mypyc compiles type-annotated Python to C extensions using the same type analysis as mypy. No new syntax, no new language -- just your existing typed Python, compiled ahead of time.

```python
# Already valid typed Python -- mypyc compiles this to C
def advance(dt: float, n: int, bodies: list[Body], pairs: list[BodyPair]) -> None:
    dx: float
    dy: float
    dz: float
    dist_sq: float
    dist: float
    mag: float
    for _ in range(n):
        for (r1, v1, m1), (r2, v2, m2) in pairs:
            dx = r1[0] - r2[0]
            dy = r1[1] - r2[1]
            dz = r1[2] - r2[2]
            dist_sq = dx * dx + dy * dy + dz * dz
            dist = math.sqrt(dist_sq)
            mag = dt / (dist_sq * dist)
            # ...
```

The difference from the baseline: explicit type declarations on every local variable so mypyc can use C primitives instead of Python objects, and decomposing `** (-1.5)` into `sqrt()` + arithmetic to avoid slow power dispatch. That's it -- no special decorators, no new build system beyond `mypycify()`.

The mypy project itself -- ~100k+ lines of Python -- achieved a <a href="https://github.com/mypyc/mypyc" target="_blank">4x end-to-end speedup</a> by compiling with mypyc. The official docs say "1.5x to 5x" for existing annotated code, "5x to 10x" for code tuned for compilation. The spectral-norm result (14x) lands above that range because the inner loop is pure arithmetic that mypyc compiles directly to C. On our dict-heavy JSON pipeline, mypyc hit 2.3x on pre-parsed dicts -- closer to the expected floor.

The constraint: mypyc supports a subset of Python. Dynamic patterns like `**kwargs`, `getattr` tricks, and heavily duck-typed code will compile but won't be optimized -- they fall back to slow generic paths. But if your code already passes mypy strict mode, mypyc is the lowest-effort compilation rung on the ladder.

---

## Rung 3: NumPy

**Cost: knowing NumPy. Reward: up to 520x.**

<div class="bench-table">

| | Spectral-norm |
|---|---|
| CPython 3.14 | 14,046ms |
| NumPy | 27ms (**520x**) |

</div>

520x. Faster than our single-threaded Rust at 154x on the same problem -- though NumPy delegates to BLAS, which uses multiple cores.

Spectral-norm is matrix-vector multiplication. NumPy pre-computes the matrix once and delegates to BLAS (Apple Accelerate on macOS):

```python
a = build_matrix(n)
for _ in range(10):
    v = a.T @ (a @ u)
    u = a.T @ (a @ v)
```

Each `@` is a single call to hand-optimized BLAS with SIMD and multithreading. NumPy trades O(N) memory for O(N^2) memory -- it stores the full 2000x2000 matrix (30MB) -- but the computation is done in compiled C/C++ (Apple Accelerate on macOS, OpenBLAS or MKL on Linux), not Python.

This is the lesson people miss when they say "Python is slow." Python the loop runner is slow. Python the orchestrator of compiled libraries is as fast as anything.

The constraint: your problem must fit vectorized operations. Element-wise math, matrix algebra, reductions -- NumPy handles these. Irregular access patterns, conditionals per element, recursive structures -- it doesn't.

---

## Rung 4: Numba

**Cost: `@njit` + restructuring data into NumPy arrays. Reward: 56-135x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.14 | 1,242ms | 14,046ms |
| Numba @njit | 22ms (**56x**) | 104ms (**135x**) |

</div>

Numba JIT-compiles decorated functions to machine code via LLVM:

```python
@njit(cache=True)
def advance(dt, n, pos, vel, mass):
    for i in range(n):
        for j in range(i + 1, n):
            dx = pos[i, 0] - pos[j, 0]
            dy = pos[i, 1] - pos[j, 1]
            dz = pos[i, 2] - pos[j, 2]
            dist = sqrt(dx * dx + dy * dy + dz * dz)
            mag = dt / (dist * dist * dist)
            vel[i, 0] -= dx * mag * mass[j]
            # ...
```

One decorator. Restructure data into NumPy arrays. The constraint: Numba works best with NumPy arrays and numeric types. It has limited support for typed dicts, typed lists, and `@jitclass`, but strings and general Python objects are largely out of reach. It's a scalpel, not a saw.

---

## Rung 5: Cython

**Cost: learning C's mental model, expressed in Python syntax. Reward: 99-124x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.14 | 1,242ms | 14,046ms |
| Cython | 10ms (**124x**) | 142ms (**99x**) |

</div>

124x on n-body. Within 10% of Rust. But here's the thing about this rung:

**My first Cython n-body got 10.5x.** Same Cython, same compiler. The final version got 124x. The difference was three landmines, none of which produced warnings:

- Cython's `**` operator with float exponents. Even with typed doubles and `-ffast-math`, `x ** 0.5` is 40x slower than `sqrt(x)` in Cython -- the operator goes through a slow dispatch path instead of compiling to C's `sqrt()`. The n-body baseline uses `** (-1.5)`, which can't be replaced with a single `sqrt()` call -- it required decomposing the formula into `sqrt()` + arithmetic. **7x penalty on the overall benchmark.**
- Precomputed pair index arrays prevent the C compiler from unrolling the nested loop. **2x penalty.** The "clever" version is slower.
- Missing `@cython.cdivision(True)` inserts a zero-division check before every floating-point divide in the inner loop. Millions of branches that are never taken.

Cython's promise is that it "makes writing C extensions for Python as easy as Python itself." In practice that means: learn C's mental model, express it in Python syntax, and use the annotation report (`cython -a`) to verify the compiler did what you think. The full story is in <a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/cython-minefield.md" target="_blank">The Cython Minefield</a>.

The reward is real -- 99-124x, matching compiled languages. But the failure mode is silent. All three landmines cost you silently, and the annotation report is the only way to catch them.

---

## Rung 6: The New Wave

**Cost: new toolchains, rough edges, ecosystem gaps. Reward: 26-198x.**

Three tools promise to compile Python (or Python-like code) to native machine code. I tested all three.

<div class="bench-table">

| | N-body | Speedup | Spectral-norm | Speedup | The catch |
|---|---|---|---|---|---|
| Codon 0.19 | 47ms | **26x** | 99ms | **142x** | Own runtime, limited stdlib, limited CPython interop |
| Mojo nightly | 16ms | **78x** | 118ms | **119x** | New language (pre-1.0), full rewrite required |
| Taichi 1.7 | 16ms | **78x** | 71ms | **198x** | Python 3.13 only (no 3.14 wheels) |

</div>

The numbers are real. The developer experience is rough. Codon can't import your existing code. Mojo is a new language wearing Python's clothes. Taichi has the best spectral-norm result (198x) but **doesn't ship wheels for Python 3.14** -- its numbers above were benchmarked on a separate Python 3.13 environment. That's the compromise with these tools: if your runtime doesn't keep up with CPython releases, you're stuck on an old version or juggling multiple environments. (<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/new-wave-compilers.md" target="_blank">Full deep dive with code and DX verdicts</a>)

None are drop-in. All are worth watching.

---

## Rung 7: Rust via PyO3

**Cost: learning Rust. Reward: 113-154x.**

<div class="bench-table">

| | N-body | Spectral-norm |
|---|---|---|
| CPython 3.14 | 1,242ms | 14,046ms |
| Rust (PyO3) | 11ms (**113x**) | 91ms (**154x**) |

</div>

The top of the ladder. But notice: on n-body, Cython at 10ms vs Rust at 11ms -- they're essentially tied. Both compiled to native machine code. The remaining difference is noise, not a fundamental language gap.

The real Rust advantage isn't raw speed -- it's **pipeline ownership**. When Rust parses JSON directly with serde into typed structs, it never creates a Python dict. It bypasses the Python object system entirely. That matters more on the next benchmark.

---

## The Ceiling

The Benchmarks Game problems are pure compute: tight loops, no I/O, no data structures beyond arrays. Most Python code looks nothing like that. So I built a third benchmark: load 100K JSON events, filter, transform, aggregate per user. Dicts, strings, datetime parsing -- the kind of code that makes Numba useless and makes Cython fight the Python object system.

First, every tool starts from pre-parsed Python dicts -- same input, same work:

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.14 | 48ms | 1.0x | Nothing |
| Mypyc | 21ms | 2.3x | Type annotations |
| Cython (dict optimized) | 12ms | 4.1x | Days of annotation work |

</div>

4.1x. Not 50x. The bottleneck is **Python dict access**. Even Cython's fully optimized version -- `@cython.cclass`, C arrays for counters, direct CPython C-API calls (`PyList_GET_ITEM`, `PyDict_GetItem` with borrowed refs) -- still reads input dicts through the Python C API.

But wait -- why are we feeding Cython Python dicts at all? `json.loads()` takes ~57ms to create those dicts. That's more than the entire baseline pipeline. What if Cython reads the raw bytes itself?

I wrote a second Cython pipeline that calls <a href="https://github.com/ibireme/yyjson" target="_blank">yyjson</a> -- a general-purpose C JSON parser, comparable to Rust's serde_json. Both are schema-agnostic: they parse any valid JSON, not just our event format. Cython walks the parsed tree with C pointers, filters and aggregates into C structs, and builds Python dicts only for the final output. For Rust, idiomatic serde with zero-copy deserialization. Both own the data end-to-end:

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.14 (json.loads + pipeline) | 105ms | 1.0x | Nothing |
| Mypyc (json.loads + pipeline) | 77ms | 1.4x | Type annotations |
| Cython (json.loads + pipeline) | 67ms | 1.6x | C-API dict access |
| Rust (serde, from bytes) | 21ms | **5.0x** | New language + bindings |
| Cython (yyjson, from bytes) | 17ms | **6.3x** | C library + Cython declarations |

</div>

**6.3x for Cython, 5.0x for Rust.** The ceiling was never the pipeline code -- it was `json.loads()`. Both approaches use general-purpose JSON parsers -- yyjson on the Cython side, serde on the Rust side -- and both avoid Python objects entirely in the hot loop: Cython walks yyjson's C tree into C structs, Rust deserializes into native structs via serde.

I'm not claiming Cython is faster than Rust or vice versa. A sufficiently motivated person could make either one faster -- swap parsers, tune allocators, restructure the pipeline. The point isn't which tool wins this specific benchmark. The point is *how many rungs you're willing to climb*. Both land in the same neighborhood once you bypass `json.loads()`. The code is at <a href="https://github.com/cemrehancavdar/faster-python-bench" target="_blank">faster-python-bench</a>.

---

## The Full Report Card

### N-body (500K iterations, tight floating-point loops)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.10 | 1,663ms | 0.75x | Old version |
| CPython 3.14 | 1,242ms | 1.0x | Nothing |
| CPython 3.14t | 1,513ms | 0.82x | GIL-free but slower single-thread |
| Mypyc | 518ms | 2.4x | Type annotations |
| GraalPy | 211ms | 5.9x | Python 3.12 only, ecosystem compatibility |
| PyPy | 98ms | 13x | Ecosystem compatibility |
| Codon | 47ms | 26x | Separate runtime, limited stdlib |
| Numba | 22ms | 56x | `@njit` + NumPy arrays |
| Taichi | 16ms | 78x | Python 3.13 only (no 3.14 wheels) |
| Mojo | 16ms | 78x | New language + toolchain |
| Cython | 10ms | 124x | C knowledge + landmines |
| Rust (PyO3) | 11ms | 113x | Learning Rust |

</div>

### Spectral-norm (N=2000, matrix-vector multiply)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.10 | 16,826ms | 0.83x | Old version |
| CPython 3.14 | 14,046ms | 1.0x | Nothing |
| CPython 3.14t | 14,551ms | 0.97x | GIL-free but slower single-thread |
| Mypyc | 990ms | 14x | Type annotations |
| GraalPy | 212ms | 66x | Python 3.12 only, ecosystem compatibility |
| PyPy | 1,065ms | 13x | Ecosystem compatibility |
| Codon | 99ms | 142x | Separate runtime, limited stdlib |
| Numba | 104ms | 135x | `@njit` + NumPy arrays |
| Mojo | 118ms | 119x | New language + toolchain |
| Rust (PyO3) | 91ms | 154x | Learning Rust |
| Cython | 142ms | 99x | C knowledge + landmines |
| Taichi | 71ms | 198x | Python 3.13 only (no 3.14 wheels) |
| NumPy | 27ms | 520x | Knowing NumPy + O(N^2) memory |

</div>

### JSON pipeline (100K events, end-to-end from raw bytes)

<div class="bench-table">

| Approach | Time | Speedup | What it costs you |
|---|---|---|---|
| CPython 3.14 (json.loads + pipeline) | 105ms | 1.0x | Nothing |
| Mypyc (json.loads + pipeline) | 77ms | 1.4x | Type annotations |
| Cython (json.loads + pipeline) | 67ms | 1.6x | C-API dict access |
| Rust (serde, from bytes) | 21ms | 5.0x | New language + bindings |
| Cython (yyjson, from bytes) | 17ms | 6.3x | C library + Cython declarations |

</div>

---

## When to Stop Climbing

The effort curve is exponential. Mypyc (2.4-14x) costs type annotations. PyPy/GraalPy (6-66x) costs a binary swap. Numba (56x) costs a decorator and data restructuring. Cython (99-124x) costs days and C knowledge. Rust (113-154x) costs learning a new language. The jump from 56x to 113x is a 2x improvement that costs 100x more effort.

**Upgrade first.** 3.10 to 3.11 gives you 1.4x for free.

**Mypyc for typed codebases.** If your code already passes mypy strict, compile it. 2.4x on n-body, 14x on spectral-norm, for almost no work.

**NumPy for vectorizable math.** If your problem is matrix algebra or element-wise operations, stop reading. `a.T @ (a @ u)` beat everything including Rust.

**Numba for numeric loops.** `@njit` gives you 56-135x with one decorator and honest error messages.

**Cython if you know C.** 99-124x is real, but the failure mode is silent slowness.

**Rust for pipeline ownership.** On pure compute, Cython and Rust are neck and neck. The real advantage is when Rust owns the data flow end-to-end.

**PyPy or GraalPy for pure Python.** 6-66x for zero code changes is remarkable, if your dependencies support it. GraalPy's spectral-norm result (66x) rivals compiled solutions.

**Most code doesn't need any of this.** The pipeline benchmark -- the most realistic of the three -- topped out at 4.1x when starting from Python dicts. 6.3x when Cython called yyjson and owned the bytes. If your hot path is `dict[str, Any]`, the answer might be "stop creating dicts," not "change the language." And if your code is I/O bound, none of this matters at all.

<a href="https://github.com/cemrehancavdar/faster-python-bench/blob/main/docs/profiling.md" target="_blank">Profile before you optimize.</a> `cProfile` to find the function. `line_profiler` to find the line. Then pick the right rung.

**Not covered:** <a href="https://nuitka.net/" target="_blank">Nuitka</a> (Python-to-C compiler, mostly used for packaging -- speedups are in the Mypyc range), <a href="https://pythran.readthedocs.io/" target="_blank">Pythran</a> (NumPy-focused AOT compiler, niche), <a href="https://github.com/spylang/spy" target="_blank">SPy</a> (Antonio Cuni's static Python dialect -- not ready yet but worth watching), and <a href="https://github.com/facebookincubator/cinderx" target="_blank">CinderX</a> (Meta's performance-oriented CPython fork -- not ready yet).

*Found an error? <a href="https://github.com/cemrehancavdar/faster-python-bench/pulls" target="_blank">Open a PR.</a>*
