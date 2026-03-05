---
title: "Your Framework Doesn't Matter"
date: 2026-02-19T20:00:00
type: post
tags: [python, benchmark, web, performance]
draft: false
subtitle: "or: How I Learned to Stop Worrying and Love the Framework"
description: "I instrumented a FastAPI app and measured where time actually goes. Network is 69-83% of what users experience. Framework overhead is 0.2-0.8%. Your framework choice doesn't matter as much as you think."
---

Last week I [benchmarked four web frameworks](/2026/02/10/framework-benchmark/) and found that BlackSheep is 2x faster than FastAPI. A Rust-based server and JSON serializer pushed Python within striking distance of Go. Impressive numbers.

But I kept thinking: does any of this matter? Those benchmarks measured localhost throughput with no database and no network. That's not what users experience. A real API request crosses the internet, hits a framework, queries a database through an ORM, serializes the result, and travels back. How much of that time is actually the framework?

So I built a real app, deployed it, and measured every phase.

---

## The App

A book catalog API. FastAPI + SQLAlchemy 2.0 (async) + asyncpg + Uvicorn. The standard Python stack that a developer following the FastAPI docs would use. No exotic dependencies, no optimization tricks.

Three tables: **Publisher** -> **Author** -> **Book**. Seeded with 4,215 real books from the Open Library API: Agatha Christie, Dostoevsky, Penguin Books, real data with real-world cardinality.

Deployed to <a href="https://fly.io" target="_blank">Fly.io</a> on a shared-cpu-1x machine with 512MB RAM and Postgres 17, both in Amsterdam. The cheapest setup you'd use for a side project.

Four endpoints:

1. **`GET /api/health`** returns `{"status": "ok"}`. No database, no ORM, no serialization. Pure framework overhead.
2. **`GET /api/books/{id}`** single book with author details. 4 SQL queries via `selectinload`.
3. **`GET /api/books?page=1&per_page=100`** 100 books with full details. 5 queries, `selectinload`.
4. **`GET /api/books/n-plus-one?page=1&per_page=100`** same data as #3, but with the classic N+1 bug. **302 queries** (2 + 100 x 3 individual SELECTs).

Endpoint #4 is the "what not to do" scenario. Same response, same data, but instead of letting SQLAlchemy batch the loads, each book triggers separate queries for its author, publisher, and sibling books.

## How I Measured

Every response carries timing headers measured with `time.perf_counter()`. The database layer uses SQLAlchemy's `before_cursor_execute` / `after_cursor_execute` events to split ORM overhead from raw driver time. A `contextvars.ContextVar` stores per-request timings so nothing leaks between concurrent requests.

The client measures total round-trip time. Network = client total - server total.

I ran 200 requests per endpoint from Turkey to Amsterdam (~57ms baseline RTT), with 30 warmup requests discarded. All numbers below are medians.

## Where Does Server Time Go?

Let's start with what happens inside the server. No network, just the work Python does.

<style>
.lc-chart { margin: 24px 0; }
.lc-row { margin: 12px 0; }
.lc-label {
  font-size: 0.85rem;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.lc-bar {
  display: flex;
  height: 28px;
  border-radius: 3px;
  background: var(--border);
}
.lc-bar span {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 600;
  white-space: nowrap;
  color: #fff;
  min-width: 0;
  position: relative;
  cursor: default;
}
.lc-bar span:first-child { border-radius: 3px 0 0 3px; }
.lc-bar span:last-child { border-radius: 0 3px 3px 0; }
.lc-bar span.lc-narrow { font-size: 0; }
.lc-bar span::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--text);
  color: var(--bg);
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 500;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 10;
}
.lc-bar span:hover::after {
  opacity: 1;
}
.lc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0 8px;
  font-size: 0.8rem;
  color: var(--text-dim);
}
.lc-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lc-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.lc-meta {
  font-size: 0.75rem;
  color: var(--text-dim);
  margin-top: 2px;
}
.lc-network { background: #94b0cc; }
.lc-db { background: #b8a09b; }
.lc-orm { background: #c5bb9e; color: #555 !important; }
.lc-serialize { background: #a3bca8; color: #555 !important; }
.lc-framework { background: #c26356; }
.lc-encode { background: #b5bfb0; color: #555 !important; }
.lc-bar span { transition: width 0.3s ease; }
.lc-fw-callout {
  margin: 14px 0 0;
  padding: 6px 12px;
  font-size: 0.85rem;
  color: #c26356;
  border-left: 3px solid #c26356;
}

.lc-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 16px 0 12px;
}
.lc-presets button {
  font-family: inherit;
  font-size: 0.8rem;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg);
  color: var(--text-dim);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.lc-presets button:hover {
  color: var(--text);
  border-color: var(--text-dim);
}
.lc-presets button.active {
  color: var(--text);
  border-color: var(--text);
  font-weight: 600;
}
</style>

<div class="lc-chart">
<div class="lc-legend">
  <span class="lc-legend-item"><span class="lc-legend-dot lc-db"></span>DB Driver</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-orm"></span>ORM</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-serialize"></span>Serialize</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-encode"></span>Encode</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-framework"></span>Framework</span>
</div>

<div class="lc-row">
  <div class="lc-label">Health check (no DB, no work) <span class="lc-meta">0.3ms server, 0 queries</span></div>
  <div class="lc-bar">
    <span class="lc-db lc-narrow" style="width:0%" data-tip="DB Driver: 0ms (0%)"></span>
    <span class="lc-orm lc-narrow" style="width:0%" data-tip="ORM: 0ms (0%)"></span>
    <span class="lc-serialize lc-narrow" style="width:5.6%" data-tip="Serialize: 0.02ms (6%)"></span>
    <span class="lc-encode" style="width:11.9%" data-tip="Encode: 12%">0.04ms</span>
    <span class="lc-framework" style="width:81.8%" data-tip="Framework: 82%">0.25ms</span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">Single book + author <span class="lc-meta">11.5ms server, 4 queries</span></div>
  <div class="lc-bar">
    <span class="lc-db" style="width:52.1%" data-tip="DB Driver: 52%">6.0ms</span>
    <span class="lc-orm" style="width:39.7%" data-tip="ORM: 40%">4.6ms</span>
    <span class="lc-serialize lc-narrow" style="width:1.3%" data-tip="Serialize: 0.1ms (1%)"></span>
    <span class="lc-encode lc-narrow" style="width:0.6%" data-tip="Encode: 0.1ms (1%)"></span>
    <span class="lc-framework lc-narrow" style="width:4.3%" data-tip="Framework: 0.5ms (4%)"></span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">100 books, optimized <span class="lc-meta">30.2ms server, 5 queries</span></div>
  <div class="lc-bar">
    <span class="lc-db" style="width:35.1%" data-tip="DB Driver: 35%">10.6ms</span>
    <span class="lc-orm" style="width:46.9%" data-tip="ORM: 47%">14.2ms</span>
    <span class="lc-serialize" style="width:10.1%" data-tip="Serialize: 10%">3.1ms</span>
    <span class="lc-encode lc-narrow" style="width:2.4%" data-tip="Encode: 0.7ms (2%)"></span>
    <span class="lc-framework lc-narrow" style="width:2.5%" data-tip="Framework: 0.7ms (3%)"></span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">100 books, N+1 queries <span class="lc-meta">491.9ms server, 302 queries</span></div>
  <div class="lc-bar">
    <span class="lc-db" style="width:67.2%" data-tip="DB Driver: 67%">330.4ms</span>
    <span class="lc-orm" style="width:30.9%" data-tip="ORM: 31%">152.1ms</span>
    <span class="lc-serialize lc-narrow" style="width:0.5%" data-tip="Serialize: 2.6ms (1%)"></span>
    <span class="lc-encode lc-narrow" style="width:0.1%" data-tip="Encode: 0.7ms (0%)"></span>
    <span class="lc-framework lc-narrow" style="width:0.3%" data-tip="Framework: 1.3ms (0%)"></span>
  </div>
</div>
</div>

*Hover over any segment for percentages. Bars don't sum to exactly 100%. A small residual (1-3%) falls between the timed sections.*

The health check tells the story immediately. When there's no database, the framework *is* the server, 82% of 0.3ms. But the moment you add real work, it disappears. For the optimized 100-book query, the DB driver and ORM together account for 82% of server time. Serialization is 10%. The framework (FastAPI's routing, middleware, dependency injection) is 2-3%. For the single book endpoint, it's 4%.

The N+1 scenario is brutal. Same data, same response, but 302 queries instead of 5. Server time goes from 30ms to 492ms, a **16x increase**, because each of those 302 queries pays a round-trip to Postgres and an ORM hydration cost.

But this is still only the server's perspective. What does the user actually experience?

## Now Zoom Out

Same four endpoints, but now we include what happens before and after the server: DNS, TCP, TLS, request travel, response travel, all lumped together as "Network."

Pick a distance to see how it changes the picture:

<div class="lc-chart" id="act2-chart">
<div class="lc-presets">
  <button data-rtt="5">Same building</button>
  <button data-rtt="15">Same city</button>
  <button data-rtt="40">Across Europe</button>
  <button data-rtt="57" class="active">Ankara → Amsterdam</button>
  <button data-rtt="150">Other continent</button>
</div>

<div class="lc-legend">
  <span class="lc-legend-item"><span class="lc-legend-dot lc-network"></span>Network</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-db"></span>DB Driver</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-orm"></span>ORM</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-serialize"></span>Serialize</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-encode"></span>Encode</span>
  <span class="lc-legend-item"><span class="lc-legend-dot lc-framework"></span>Framework</span>
</div>

<div class="lc-row">
  <div class="lc-label">Health check (no DB, no work) <span class="lc-meta" id="a2-s0-meta">69.6ms total</span></div>
  <div class="lc-bar">
    <span class="lc-network" id="a2-s0-net" style="width:99.4%" data-tip="Network: 99%">69.2ms</span>
    <span class="lc-db lc-narrow" id="a2-s0-db" style="width:0%" data-tip="DB Driver: 0ms (0%)"></span>
    <span class="lc-orm lc-narrow" id="a2-s0-orm" style="width:0%" data-tip="ORM: 0ms (0%)"></span>
    <span class="lc-serialize lc-narrow" id="a2-s0-ser" style="width:0%" data-tip="Serialize: 0ms (0%)"></span>
    <span class="lc-encode lc-narrow" id="a2-s0-enc" style="width:0.1%" data-tip="Encode: 0ms (0.1%)"></span>
    <span class="lc-framework lc-narrow" id="a2-s0-fw" style="width:0.4%" data-tip="Framework: 0.2ms (0.4%)"></span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">Single book + author <span class="lc-meta" id="a2-s1-meta">68.8ms total</span></div>
  <div class="lc-bar">
    <span class="lc-network" id="a2-s1-net" style="width:82.6%" data-tip="Network: 83%">56.9ms</span>
    <span class="lc-db" id="a2-s1-db" style="width:8.7%" data-tip="DB Driver: 9%">6.0ms</span>
    <span class="lc-orm" id="a2-s1-orm" style="width:6.6%" data-tip="ORM: 7%">4.6ms</span>
    <span class="lc-serialize lc-narrow" id="a2-s1-ser" style="width:0.2%" data-tip="Serialize: 0.1ms (0.2%)"></span>
    <span class="lc-encode lc-narrow" id="a2-s1-enc" style="width:0.1%" data-tip="Encode: 0.1ms (0.1%)"></span>
    <span class="lc-framework lc-narrow" id="a2-s1-fw" style="width:0.7%" data-tip="Framework: 0.5ms (0.7%)"></span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">100 books, optimized <span class="lc-meta" id="a2-s2-meta">97.0ms total</span></div>
  <div class="lc-bar">
    <span class="lc-network" id="a2-s2-net" style="width:68.6%" data-tip="Network: 69%">66.6ms</span>
    <span class="lc-db" id="a2-s2-db" style="width:10.9%" data-tip="DB Driver: 11%">10.6ms</span>
    <span class="lc-orm" id="a2-s2-orm" style="width:14.6%" data-tip="ORM: 15%">14.2ms</span>
    <span class="lc-serialize" id="a2-s2-ser" style="width:3.1%" data-tip="Serialize: 3%">3.1ms</span>
    <span class="lc-encode lc-narrow" id="a2-s2-enc" style="width:0.7%" data-tip="Encode: 0.7ms (0.7%)"></span>
    <span class="lc-framework lc-narrow" id="a2-s2-fw" style="width:0.8%" data-tip="Framework: 0.7ms (0.8%)"></span>
  </div>
</div>

<div class="lc-row">
  <div class="lc-label">100 books, N+1 queries <span class="lc-meta" id="a2-s3-meta">613.2ms total</span></div>
  <div class="lc-bar">
    <span class="lc-network" id="a2-s3-net" style="width:13.4%" data-tip="Network: 13%">82.2ms</span>
    <span class="lc-db" id="a2-s3-db" style="width:53.9%" data-tip="DB Driver: 54%">330.4ms</span>
    <span class="lc-orm" id="a2-s3-orm" style="width:24.8%" data-tip="ORM: 25%">152.1ms</span>
    <span class="lc-serialize lc-narrow" id="a2-s3-ser" style="width:0.4%" data-tip="Serialize: 2.6ms (0.4%)"></span>
    <span class="lc-encode lc-narrow" id="a2-s3-enc" style="width:0.1%" data-tip="Encode: 0.7ms (0.1%)"></span>
    <span class="lc-framework lc-narrow" id="a2-s3-fw" style="width:0.2%" data-tip="Framework: 1.3ms (0.2%)"></span>
  </div>
</div>

<div class="lc-fw-callout" id="a2-fw-callout">Framework is <strong id="a2-fw-pct">0.2–0.9%</strong> of total response time</div>
</div>

*Hover over any segment for percentages. Server timings are constant, only network changes.*

There it is. The health check, where the framework has nothing to do except route and respond, is **99% network**. The server finishes in 0.3ms. The user waits 70ms.

For a single book lookup, **83% of what the user waits for is the network**. The entire server (framework, ORM, database, serialization, JSON encoding) is the remaining 17%. The framework specifically is 0.7%.

For 100 books with proper queries, network is 69%. The server does more work (30ms vs 12ms), but the user still spends most of their time waiting for packets to cross the internet.

These numbers default to my setup. I live in Ankara, Turkey, and my closest Fly.io region is Amsterdam. Try the presets above to see how distance changes the picture. Even in the best case (same building, 5ms) network is still 30% of a single book lookup. And most SaaS products aren't running multi-region deployments with edge nodes. They have one server in one region.

The N+1 scenario flips everything. Network drops to 13%, not because the network got faster, but because the server got so slow (492ms) that it dwarfs the network time. This is the only scenario where server-side code meaningfully impacts user experience. And the cause isn't the framework, it's 302 queries instead of 5.

## Framework Overhead Across All Scenarios

| Scenario | Total | Framework | Framework % |
|---|---|---|---|
| Health check (no DB) | 69.6ms | 0.2ms | 0.4% |
| Single book | 68.8ms | 0.5ms | 0.7% |
| 100 books (optimized) | 97.0ms | 0.7ms | 0.8% |
| 100 books (N+1) | 613.2ms | 1.3ms | 0.2% |

The health check is the best case for the framework: no database, no ORM, no serialization. The server does almost nothing. And still, framework overhead is 0.2ms out of a 70ms request. FastAPI's routing, middleware, dependency injection, and ASGI handling cost 0.2-1.3ms across all scenarios. That's the thing benchmarks compare when they say "FastAPI vs BlackSheep" or "Python vs Go." The thing that accounts for less than 1% of what users experience.

In my [previous benchmark](/2026/02/10/framework-benchmark/), BlackSheep was 2x faster than FastAPI. That 2x difference applies to 0.7% of the total response time. Switching frameworks would save roughly 0.25ms on a 69ms request.

## Putting Traffic in Perspective

Let's say your API gets 1 million requests per day. That sounds like a lot. It's 12 requests per second.

| Daily Requests | Avg req/s | Peak req/s (3x avg) |
|---|---|---|
| 100,000 | 1.2 | 3.5 |
| 1,000,000 | 11.6 | 35 |
| 10,000,000 | 115.7 | 347 |

Levels.fyi, a site with 1-2 million monthly uniques and over $1M ARR, runs one of its most trafficked services on <a href="https://www.levels.fyi/blog/scaling-to-millions-with-google-sheets.html" target="_blank">a single Node.js instance serving 60K requests per hour</a>. That's 17 req/s. FastAPI handles 46,000 req/s on a single worker in my benchmarks. You have roughly 2,700x headroom.

In 2016, Stack Overflow served <a href="https://nickcraver.com/blog/2016/02/17/stack-overflow-the-architecture-2016-edition/" target="_blank">209 million HTTP requests per day</a> (about 2,400 req/s average) on 9 web servers. Nick Craver said they'd unintentionally tested running on a single server, and it worked.

Framework throughput differences don't matter when your actual traffic is three orders of magnitude below capacity.

## What I Didn't Measure

This is a sequential measurement from a single client, no concurrent load. Under concurrency, connection pooling, async scheduling, and GIL contention could change the server-side breakdown. The "Framework" bucket lumps together Uvicorn, Starlette, and FastAPI. I didn't separate them. "Network" lumps DNS, TLS, TCP, and raw packet travel. Response sizes are pre-compression (the real responses would be smaller over gzip).

At scale, a faster framework means fewer servers, that's real cost savings. But "at scale" means hundreds of thousands of requests per second, not millions per day. And long before you get there, you'll have optimized your queries, added caching, moved to handwritten SQL, and maybe even forked your runtime. <a href="https://github.com/facebookincubator/cinder" target="_blank">Facebook built their own Python</a> before they worried about framework overhead.

All measurements: 200 samples each, medians, from Turkey to Amsterdam. The raw data is in the repository.

## What I Learned

**Deploy closer to your users.** For well-written queries, 69-83% of response time is packets crossing the internet. No framework optimization changes this. If your server is in Amsterdam and your users are in Ankara, they're waiting 57ms before your code even runs. Move the server, or put a cache at the edge.

**Fix your queries, not your framework.** The N+1 bug turned a 97ms response into a 613ms one, 6.3x slower, and framework overhead was still only 0.2%. Switching from FastAPI to BlackSheep would save 0.25ms. Fixing the N+1 bug saves 516ms. Profile your queries. Add `selectinload`. Use `EXPLAIN ANALYZE`. That's where the seconds are.

**Pick your framework for everything except speed.** Framework benchmarks compare the one component that doesn't matter (0.2-0.8% of total time) under conditions that don't exist (localhost, no database, no network). Pick for developer experience, documentation, ecosystem, and hiring. The framework that lets you ship faster is the fast framework.

If you want to see what actually makes a website fast in practice, Wes Bos has <a href="https://www.youtube.com/watch?v=-Ln-8QM8KhQ" target="_blank">a great breakdown</a>. Hint: it's not the framework.

---

Benchmarking is hard. I'm sure I got something wrong, missed an important variable, or made an assumption that doesn't hold. All the code, measurement scripts, and raw timing data are in the <a href="https://github.com/cemrehancavdar/api-lifecycle" target="_blank">repository</a>. Please try to break it. If you find a flaw in the methodology, a timing error, or a scenario that would change the conclusions, I genuinely want to hear about it.


<script>
(function () {
  var scenarios = [
    { key: "s0", server: 0.303, db: 0, orm: 0, ser: 0.017, enc: 0.036, fw: 0.248 },
    { key: "s1", server: 11.523, db: 6.001, orm: 4.575, ser: 0.145, enc: 0.065, fw: 0.500 },
    { key: "s2", server: 30.231, db: 10.599, orm: 14.174, ser: 3.053, enc: 0.720, fw: 0.742 },
    { key: "s3", server: 491.918, db: 330.353, orm: 152.146, ser: 2.587, enc: 0.690, fw: 1.296 }
  ];

  var parts = ["net", "db", "orm", "ser", "enc", "fw"];
  var partLabels = ["Network", "DB Driver", "ORM", "Serialize", "Encode", "Framework"];
  var narrowThreshold = 4;

  function fmt(v) { return v < 10 ? v.toFixed(1) : Math.round(v).toString(); }

  function updateChart(rtt) {
    var fwPcts = [];
    scenarios.forEach(function (s) {
      var total = rtt + s.server;
      var values = { net: rtt, db: s.db, orm: s.orm, ser: s.ser, enc: s.enc, fw: s.fw };

      parts.forEach(function (p, i) {
        var el = document.getElementById("a2-" + s.key + "-" + p);
        if (!el) return;
        var ms = values[p];
        var pct = (ms / total) * 100;
        el.style.width = pct + "%";

        if (pct >= narrowThreshold) {
          el.textContent = fmt(ms) + "ms";
          el.classList.remove("lc-narrow");
        } else {
          el.textContent = "";
          el.classList.add("lc-narrow");
        }

        if (pct >= narrowThreshold) {
          el.setAttribute("data-tip", partLabels[i] + ": " + Math.round(pct) + "%");
        } else {
          el.setAttribute("data-tip", partLabels[i] + ": " + fmt(ms) + "ms (" + pct.toFixed(1) + "%)");
        }
      });

      fwPcts.push((s.fw / total) * 100);

      var meta = document.getElementById("a2-" + s.key + "-meta");
      if (meta) meta.textContent = fmt(total) + "ms total";
    });

    var fwMin = Math.min.apply(null, fwPcts);
    var fwMax = Math.max.apply(null, fwPcts);
    var callout = document.getElementById("a2-fw-pct");
    if (callout) callout.textContent = fwMin.toFixed(1) + "–" + fwMax.toFixed(1) + "%";
  }

  var buttons = document.querySelectorAll(".lc-presets button");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      buttons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      updateChart(parseFloat(btn.getAttribute("data-rtt")));
    });
  });

  updateChart(57);
})();
</script>
