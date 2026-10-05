import assert from "node:assert/strict";
import test from "node:test";
import worker from "../cloudflare-worker/worker.js";

function request(model, endpoint = "solve", extra = {}) {
  return new Request(`https://gateway.example/api/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: "What is 1+1?", options: ["2", "3"], model, ...extra }),
  });
}

test("both GPT-OSS models run on Cloudflare without a Groq key", async () => {
  for (const model of ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]) {
    const response = await worker.fetch(request(model), { AI: {
      async run(selected, input) {
        assert.equal(selected, `@cf/${model}`);
        assert.equal(input.max_tokens, 2048);
        return { response: '{"selected_indices":[1]}' };
      },
    } });
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.model, model);
    assert.equal(data.provider, "Cloudflare Workers AI");
  }
});

test("fill-in-the-blank uses the selected model and reads Responses API output", async () => {
  const model = "openai/gpt-oss-20b";
  const response = await worker.fetch(request(model, "solve-fib"), { AI: {
    async run(selected) {
      assert.equal(selected, `@cf/${model}`);
      return { output: [{ type: "message", content: [{ type: "output_text", text: '{"answer":"2"}' }] }] };
    },
  } });
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.answer, "2");
  assert.equal(data.model, model);
});

test("Groq fallback keeps the selected GPT-OSS model", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (_, options) => {
    const body = JSON.parse(options.body);
    assert.equal(body.model, "openai/gpt-oss-120b");
    assert.equal(body.reasoning_effort, "low");
    return Response.json({ choices: [{ message: { content: '{"selected_indices":[1]}' } }] });
  };
  try {
    const response = await worker.fetch(request("openai/gpt-oss-120b"), {
      GROQ_API_KEY: "fake-key", AI: { async run() { throw new Error("quota exceeded"); } },
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).provider, "Groq Cloud (Fallback)");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("unsupported models and image requests are rejected before inference", async () => {
  const env = { AI: { async run() { assert.fail("must not call inference"); } } };
  assert.equal((await worker.fetch(request("unknown"), env)).status, 400);
  assert.equal((await worker.fetch(request("openai/gpt-oss-120b", "solve", { image_base64:"image" }), env)).status, 400);
});

test("selected-model errors do not silently answer using Smart Hybrid", async () => {
  const response = await worker.fetch(request("openai/gpt-oss-120b"), {
    AI: { async run(model) {
      assert.equal(model, "@cf/openai/gpt-oss-120b");
      throw new Error("unavailable");
    } },
  });
  assert.equal(response.status, 500);
  assert.equal((await response.json()).error, "unavailable");
});

test("malformed answer is rejected instead of inventing option one", async () => {
  const response = await worker.fetch(request("openai/gpt-oss-120b"), {
    AI: { async run() { return { choices: [{ message: { content: '{"selected_indices":[99]}' } }] }; } },
  });
  assert.equal(response.status, 500);
});

test("default Smart Hybrid still runs Llama", async () => {
  const response = await worker.fetch(request(""), {
    AI: { async run(model) {
      assert.equal(model, "@cf/meta/llama-3.3-70b-instruct-fp8-fast");
      return { response: '{"selected_indices":[1]}' };
    } },
  });
  assert.equal(response.status, 200);
});

test("Qwen uses Groq with the server key for both endpoints", async () => {
  const previousFetch = globalThis.fetch;
  try {
    for (const endpoint of ["solve", "solve-fib"]) {
      const answer = endpoint === "solve" ? { selected_indices:[1] } : { answer:"2" };
      globalThis.fetch = async (url, options) => {
        assert.equal(url, "https://api.groq.com/openai/v1/chat/completions");
        assert.equal(options.headers.Authorization, "Bearer server-key");
        const body = JSON.parse(options.body);
        assert.equal(body.model, "qwen/qwen3.8-27b");
        assert.equal(body.reasoning_format, "hidden");
        return Response.json({ choices:[{ message:{ content:JSON.stringify(answer) } }] });
      };
      const response = await worker.fetch(request("qwen/qwen3.8-27b", endpoint), {
        GROQ_API_KEY: "server-key", AI: { async run() { assert.fail("Qwen must use Groq"); } },
      });
      assert.equal(response.status, 200);
      const data = await response.json();
      assert.equal(data.model, "qwen/qwen3.8-27b");
      assert.equal(data.provider, "Groq Cloud");
    }
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("Qwen image input is forwarded to Groq", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (_, options) => {
      const body = JSON.parse(options.body);
      const user = body.messages.find(message => message.role === "user");
      assert.equal(user.content[1].image_url.url, "data:image/png;base64,abc");
      return Response.json({ choices:[{ message:{ content:'{"selected_indices":[1]}' } }] });
  };
  try {
    const response = await worker.fetch(request("qwen/qwen3.8-27b", "solve", { image_base64:"abc" }), {
      GROQ_API_KEY: "server-key", AI: { async run() { assert.fail("must not use Cloudflare inference"); } },
    });
    assert.equal(response.status, 200);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("Qwen cannot silently switch to Cloudflare when the Groq key is missing", async () => {
  const response = await worker.fetch(request("qwen/qwen3.8-27b"), {
    AI: { async run() { assert.fail("must not use Cloudflare inference"); } },
  });
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /GROQ_API_KEY/);
});
