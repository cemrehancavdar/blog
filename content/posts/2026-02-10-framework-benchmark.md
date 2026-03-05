---
title: "Benchmarking Gin, Elysia, BlackSheep, and FastAPI"
date: 2026-02-10T20:00:00
type: post
tags: [python, go, javascript, benchmark, web]
draft: false
description: "Docker benchmarks comparing Go, Bun, and Python web frameworks. All frameworks get 2 CPUs and 2 workers. Python is faster than you think."
---

I always felt like JavaScript and Go are the alternative languages for Python. I wouldn't compare Python to Rust or Zig. So when I keep seeing Gin vs Elysia benchmarks, I wanted to throw Python into the mix. FastAPI says it's fast right in the name. Let's find out.

Four frameworks, three languages, same Docker constraints, same endpoints.

[Source code on GitHub](https://github.com/cemrehancavdar/framework-benchmark)

**TLDR:** Python's ecosystem (Granian, orjson) makes it fast enough to beat Bun's Elysia on validation and routing. Gin (Go) still wins overall. BlackSheep > FastAPI by 2x. Full numbers and code below.

---

## The Setup

Every framework runs in a Docker container with identical constraints:

- **Server**: 2 CPUs, 512MB RAM, 2 workers
- **Client**: [wrk](https://github.com/wg/wrk) with 2 threads, 128 connections, 10 seconds per endpoint
- **Machine**: Apple M4 Pro
- **Four endpoints**: plaintext, JSON, URL params, POST validation

The "2 workers" part is important. Go uses `GOMAXPROCS=2`, Python uses 2 uvicorn workers, and Bun uses cluster mode with 2 processes. Everyone gets two CPU cores and two parallel execution contexts.

Each endpoint does progressively more work:

- `/plaintext` return `"Hello, World!"` (raw I/O)
- `/json` return `{"message": "Hello, World!"}` (serialization)
- `/user/42` parse a URL param, return `{"id": "42", "name": "User 42"}` (routing)
- `POST /validate` parse JSON body, validate fields, return result (real-world work)

## The Contenders

### FastAPI (Python)

```python
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

app = FastAPI()

HELLO = "Hello, World!"


class UserInput(BaseModel):
    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=150)


@app.get("/plaintext")
async def plaintext() -> PlainTextResponse:
    return PlainTextResponse(HELLO)


@app.get("/json")
async def json_endpoint() -> dict:
    return {"message": HELLO}


@app.get("/user/{user_id}")
async def get_user(user_id: str) -> dict:
    return {"id": user_id, "name": f"User {user_id}"}


@app.post("/validate")
async def validate(body: UserInput) -> dict:
    return {"name": body.name, "age": body.age, "valid": True}
```

The crowd favorite. Pydantic models give you validation, serialization, and OpenAPI docs in one shot. It's the most productive framework here, but that productivity has a cost at runtime, which we'll see in the numbers.

### Gin (Go)

```go
package main

import (
	"fmt"
	"net/http"
	"os"
	"runtime"
	"strconv"

	"github.com/gin-gonic/gin"
)

const hello = "Hello, World!"

type ValidateInput struct {
	Name string `json:"name" binding:"required,min=1"`
	Age  int    `json:"age" binding:"required,gte=0,lte=150"`
}

func main() {
	workers := 4
	if v, err := strconv.Atoi(os.Getenv("WORKERS")); err == nil && v > 0 {
		workers = v
	}
	runtime.GOMAXPROCS(workers)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()

	r.GET("/plaintext", func(c *gin.Context) {
		c.String(http.StatusOK, hello)
	})

	r.GET("/json", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"message": hello})
	})

	r.GET("/user/:id", func(c *gin.Context) {
		id := c.Param("id")
		c.JSON(http.StatusOK, gin.H{
			"id":   id,
			"name": fmt.Sprintf("User %s", id),
		})
	})

	r.POST("/validate", func(c *gin.Context) {
		var input ValidateInput
		if err := c.ShouldBindJSON(&input); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{
			"name":  input.Name,
			"age":   input.Age,
			"valid": true,
		})
	})

	r.Run(":3000")
}
```

Gin is terse. Struct tags handle validation. The `gin.H{}` shorthand for map literals keeps handlers compact. Go's goroutine scheduler makes concurrency almost invisible. You just set `GOMAXPROCS` and everything scales.

### Elysia (Bun)

```typescript
import { Elysia, t } from "elysia";

const HELLO = "Hello, World!";
const PORT = 3000;

new Elysia()
  .get("/plaintext", () => HELLO)
  .get("/json", () => ({ message: HELLO }))
  .get("/user/:id", ({ params }) => ({
    id: params.id,
    name: `User ${params.id}`,
  }))
  .post(
    "/validate",
    ({ body }) => ({
      name: body.name,
      age: body.age,
      valid: true,
    }),
    {
      body: t.Object({
        name: t.String({ minLength: 1 }),
        age: t.Integer({ minimum: 0, maximum: 150 }),
      }),
    }
  )
  .listen(PORT);
```

The most elegant of the bunch. Elysia's API is beautifully minimal. Return an object and it becomes JSON. The TypeBox schema validation (`t.Object`, `t.String`) is declarative and type-safe. Bun's runtime makes it fast.

### BlackSheep (Python)

```python
from blacksheep import Application, Request
from blacksheep.server.responses import json as json_resp
from blacksheep.server.responses import text as text_resp

app = Application()

HELLO = "Hello, World!"


@app.router.get("/plaintext")
async def plaintext():
    return text_resp(HELLO)


@app.router.get("/json")
async def json_endpoint():
    return json_resp({"message": HELLO})


@app.router.get("/user/{user_id}")
async def get_user(user_id: str):
    return json_resp({"id": user_id, "name": f"User {user_id}"})


@app.router.post("/validate")
async def validate(request: Request):
    body = await request.json()
    name = body.get("name")
    age = body.get("age")

    if not isinstance(name, str) or not name:
        return json_resp({"error": "name must be a non-empty string"}, status=400)
    if not isinstance(age, int) or age < 0 or age > 150:
        return json_resp(
            {"error": "age must be an integer between 0 and 150"}, status=400
        )

    return json_resp({"name": name, "age": age, "valid": True})
```

Most Python developers haven't heard of BlackSheep. No magic, no heavy abstractions, manual validation. You'll see why it's here in a moment.

## Results

All numbers are requests per second, higher is better. Each framework ran with 2 workers on 2 CPUs.

| Framework | Plaintext | JSON | Params | Validate (POST) |
|---|---|---|---|---|
| **Gin** (Go) | 299,632 | 288,408 | 266,471 | 195,275 |
| **Elysia** (Bun) | 246,068 | 219,089 | 185,984 | 102,488 |
| **BlackSheep** (Python) | 152,005 | 129,958 | 128,939 | 98,829 |
| **FastAPI** (Python) | 79,785 | 66,114 | 51,560 | 45,963 |

A few things jump out.

**Gin wins everything**, which isn't surprising. Go's goroutine scheduler and compiled performance are hard to beat. But it's not a blowout against Elysia on plaintext (300k vs 246k, only 22% ahead).

**Elysia drops hard under load.** From plaintext (246k) to validate (102k), it loses 58% of its throughput. Bun is fast at raw I/O, but TypeBox validation in JavaScript is expensive relative to the baseline.

**BlackSheep is shockingly fast for Python.** 152k req/s on plaintext, and it holds up well under load, only a 35% drop to validate (99k). That validate number is close to Elysia's (102k vs 99k). A Python framework running at 96% of Bun's speed on a real workload.

**FastAPI is about half of BlackSheep** across the board. The Pydantic validation layer and middleware stack cost roughly 2x in overhead. Still, 46k req/s on validate is respectable.

## So Can BlackSheep Get Even Faster?

Two swaps. [Granian](https://github.com/emmett-framework/granian) instead of uvicorn, a Rust-based ASGI server. [orjson](https://github.com/ijl/orjson) instead of stdlib `json`, a Rust-based JSON serializer. Same application code, different plumbing:

```python
import orjson
from blacksheep import Application, Content, Request, Response
from blacksheep.server.responses import text as text_resp

app = Application(show_error_details=False)

HELLO = "Hello, World!"
CT_JSON = b"application/json"


def json_bytes_response(data: dict, status: int = 200) -> Response:
    """Build a Response from orjson-serialized bytes."""
    return Response(status, content=Content(CT_JSON, orjson.dumps(data)))


@app.router.get("/plaintext")
async def plaintext():
    return text_resp(HELLO)


@app.router.get("/json")
async def json_endpoint() -> Response:
    return json_bytes_response({"message": HELLO})


@app.router.get("/user/{user_id}")
async def get_user(user_id: str) -> Response:
    return json_bytes_response({"id": user_id, "name": f"User {user_id}"})


@app.router.post("/validate")
async def validate(request: Request) -> Response:
    body = orjson.loads(await request.read())
    name = body.get("name")
    age = body.get("age")

    if not isinstance(name, str) or not name:
        return json_bytes_response({"error": "name must be a non-empty string"}, 400)
    if not isinstance(age, int) or age < 0 or age > 150:
        return json_bytes_response(
            {"error": "age must be an integer between 0 and 150"}, 400
        )

    return json_bytes_response({"name": name, "age": age, "valid": True})
```

| Framework | Plaintext | JSON | Params | Validate (POST) |
|---|---|---|---|---|
| **Gin** (Go) | 299,632 | 288,408 | 266,471 | 195,275 |
| **Elysia** (Bun) | 246,068 | 219,089 | 185,984 | 102,488 |
| **BlackSheep+Granian+orjson** | 204,575 | 202,394 | 189,881 | 119,527 |
| **BlackSheep** (uvicorn) | 152,005 | 129,958 | 128,939 | 98,829 |
| **FastAPI** (Python) | 79,785 | 66,114 | 51,560 | 45,963 |

Yes it can. BlackSheep+Granian+orjson beats Elysia on validate (120k vs 102k) and params (190k vs 186k). The JSON endpoint improved 56%. That's what swapping `json.dumps()` for a Rust serializer does.

## What I Learned

**Python may be slower, but the ecosystem makes it fast.** The language itself isn't winning any speed contests. But Granian (Rust HTTP server), orjson (Rust JSON), and uvloop (Cython event loop) let Python compete with Bun and get within striking distance of Go. The ecosystem does the heavy lifting.

**The server matters as much as the framework.** Swapping uvicorn for Granian gave a 35% boost on plaintext without changing application code. HTTP parsing and connection management aren't free.

**Validation is the great equalizer.** Raw I/O benchmarks favor compiled languages. But once every framework has to parse JSON, validate fields, and return structured errors, the gaps shrink. BlackSheep goes from 62% of Gin on plaintext to 61% on validate. Elysia goes from 82% to 52%.

---

All the code, Dockerfiles, and raw results are in the [repository](https://github.com/cemrehancavdar/framework-benchmark). Benchmarking is hard. If you spot something unfair or wrong, please tell me.
