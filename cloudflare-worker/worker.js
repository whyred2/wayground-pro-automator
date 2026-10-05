/**
 * Wayground Pro Automator - Smart Hybrid AI Gateway (Cloudflare Worker)
 * --------------------------------------------------------------------
 * Primary:  Cloudflare Workers AI (@cf/meta/llama-3.3-70b-instruct / vision)
 *           (100% autonomous, zero external API keys needed)
 * Fallback: Groq Cloud (qwen/qwen3.8-27b via env.GROQ_API_KEY)
 *           (Activates automatically if Workers AI quota is exceeded or fails)
 */

// In-memory rate limiting tracker (per edge isolate)
const ipRateLimits = new Map();
const RATE_LIMIT_WINDOW_MS = 60 * 1000;
const MAX_REQUESTS_PER_MINUTE = 30;
const QWEN_MODEL = "qwen/qwen3.8-27b";
const SELECTABLE_MODELS = new Set(["openai/gpt-oss-120b", "openai/gpt-oss-20b", QWEN_MODEL]);

function checkRateLimit(ip) {
  const now = Date.now();
  const entry = ipRateLimits.get(ip) || { count: 0, resetAt: now + RATE_LIMIT_WINDOW_MS };

  if (now > entry.resetAt) {
    entry.count = 1;
    entry.resetAt = now + RATE_LIMIT_WINDOW_MS;
    ipRateLimits.set(ip, entry);
    return true;
  }

  if (entry.count >= MAX_REQUESTS_PER_MINUTE) {
    return false;
  }

  entry.count++;
  ipRateLimits.set(ip, entry);
  return true;
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }
  });
}

function extractJson(text) {
  if (!text) return null;
  if (typeof text === "object") return text;
  let clean = String(text).trim();
  clean = clean.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
  try {
    return JSON.parse(clean);
  } catch {
    const m = clean.match(/\{[\s\S]*\}/);
    if (m) {
      try {
        return JSON.parse(m[0]);
      } catch {}
    }
  }
  return null;
}

// ─────────────────────────────────────────────────────────────
// 1. Cloudflare Workers AI Runner (Primary)
// ─────────────────────────────────────────────────────────────
async function runWorkersAI(env, messages, imageBase64 = null) {
  if (!env.AI) {
    throw new Error("Cloudflare Workers AI binding [AI] is not configured in wrangler.toml");
  }

  // Multimodal query with image
  if (imageBase64) {
    try {
      const cleanB64 = imageBase64.replace(/^data:image\/[a-z]+;base64,/, "");
      const binary = atob(cleanB64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }

      const sysMsg = messages.find(m => m.role === "system")?.content || "";
      const userMsg = messages.find(m => m.role === "user")?.content || "";
      const combined = sysMsg ? `${sysMsg}\n\n${userMsg}` : userMsg;

      const res = await env.AI.run("@cf/meta/llama-3.2-11b-vision-instruct", {
        prompt: combined,
        image: [...bytes],
        max_tokens: 768
      });
      return res.response || "";
    } catch (vErr) {
      console.warn("Workers AI vision model failed, retrying text with Llama 3.3 70B:", vErr.message);
    }
  }

  // Text-only with flagship Llama 3.3 70B (FP8 Fast)
  const res = await env.AI.run("@cf/meta/llama-3.3-70b-instruct-fp8-fast", {
    messages: messages,
    max_tokens: 768,
    temperature: 0.0
  });

  return res.response || "";
}

// ─────────────────────────────────────────────────────────────
// 2. Groq Cloud Runner (primary for Qwen, fallback for other engines)
// ─────────────────────────────────────────────────────────────
async function runGroqAI(apiKey, messages, imageBase64 = null, model = "qwen/qwen3.8-27b") {
  if (!apiKey) {
    throw new Error("GROQ_API_KEY secret is not configured");
  }

  let userContent = messages.find(m => m.role === "user")?.content || "";
  if (imageBase64) {
    const dataUri = imageBase64.startsWith("data:") ? imageBase64 : `data:image/png;base64,${imageBase64}`;
    userContent = [
      { type: "text", text: userContent },
      { type: "image_url", image_url: { url: dataUri } }
    ];
  }

  const sysContent = messages.find(m => m.role === "system")?.content || "";

  const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: sysContent },
        { role: "user", content: userContent }
      ],
      response_format: { type: "json_object" },
      max_tokens: SELECTABLE_MODELS.has(model) ? 2048 : 768,
      ...(model === QWEN_MODEL ? { reasoning_effort: "low", reasoning_format: "hidden" } :
        SELECTABLE_MODELS.has(model) ? { reasoning_effort: "low", include_reasoning: false } : {}),
      temperature: 0.0
    })
  });

  if (!groqResp.ok) {
    const errText = await groqResp.text();
    throw new Error(`Groq API error (${groqResp.status}): ${errText}`);
  }

  const data = await groqResp.json();
  return data.choices?.[0]?.message?.content || "";
}

async function runSelectedModel(env, model, messages, imageBase64 = null) {
  if (model === QWEN_MODEL) {
    const rawOutput = await runGroqAI(env.GROQ_API_KEY, messages, imageBase64, model);
    return { rawOutput, engineUsed: "Groq Cloud" };
  }
  let inputMessages = messages;
  if (imageBase64) {
    const dataUri = imageBase64.startsWith("data:") ? imageBase64 : `data:image/png;base64,${imageBase64}`;
    inputMessages = messages.map(message => message.role === "user" ? {
      role: "user",
      content: [{ type: "text", text: message.content }, { type: "image_url", image_url: { url: dataUri } }],
    } : message);
  }
  try {
    if (!env.AI) throw new Error("Workers AI binding is not configured");
    const result = await env.AI.run(`@cf/${model}`, {
      messages: inputMessages,
      max_tokens: 2048,
      response_format: { type: "json_object" },
      reasoning_effort: "low",
    });
    const rawOutput = result.response || result.choices?.[0]?.message?.content ||
      result.output?.flatMap(item => item.content || [])
        .filter(item => item.type === "output_text").map(item => item.text).join("") || "";
    if (!extractJson(rawOutput)) throw new Error("Workers AI returned no valid JSON answer");
    return { rawOutput, engineUsed: "Cloudflare Workers AI" };
  } catch (error) {
    if (!env.GROQ_API_KEY) throw error;
    const rawOutput = await runGroqAI(env.GROQ_API_KEY, messages, imageBase64, model);
    return { rawOutput, engineUsed: "Groq Cloud (Fallback)" };
  }
}

// ─────────────────────────────────────────────────────────────
// Main Worker Handler
// ─────────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS Preflight
    if (request.method === "OPTIONS") {
      return jsonResponse({ ok: true });
    }

    // Health / Info Check
    if (url.pathname === "/" || url.pathname === "/health" || url.pathname === "/api/health") {
      return jsonResponse({
        status: "online",
        service: "wayground-ai-gateway",
        mode: "smart-hybrid",
        primary_engine: "Cloudflare Workers AI (@cf/meta/llama-3.3-70b-instruct-fp8-fast)",
        fallback_engine: env.GROQ_API_KEY ? "Groq Cloud (qwen/qwen3.8-27b)" : "None configured",
        supported_models: [...SELECTABLE_MODELS],
        qwen_provider: "Groq Cloud"
      });
    }

    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    // Rate Limiting
    const clientIP = request.headers.get("CF-Connecting-IP") || "unknown";
    if (!checkRateLimit(clientIP)) {
      return jsonResponse(
        { error: "Rate limit exceeded. Please wait 1 minute before solving more questions." },
        429
      );
    }

    try {
      // ─────────────────────────────────────────────────────────
      // Endpoint: /api/solve (Multiple-Choice Questions)
      // ─────────────────────────────────────────────────────────
      if (url.pathname === "/api/solve") {
        const body = await request.json();
        const selectedModel = body.model || "";
        if (selectedModel && !SELECTABLE_MODELS.has(selectedModel)) {
          return jsonResponse({ error: "Unsupported model" }, 400);
        }
        if (selectedModel && selectedModel !== QWEN_MODEL && body.image_base64) {
          return jsonResponse({ error: "Selected model supports text only" }, 400);
        }
        const question = (body.question || "").trim();
        const options = Array.isArray(body.options) ? body.options : [];
        const isMsq = Boolean(body.is_msq);
        const imageBase64 = body.image_base64 || null;

        if (!question && !imageBase64) {
          return jsonResponse({ error: "Question text or image is required" }, 400);
        }
        if (options.length === 0) {
          return jsonResponse({ error: "At least one option is required" }, 400);
        }

        const formattedOptions = options.map((opt, idx) => {
          const txt = typeof opt === "string" ? opt : (opt.text || opt.alt || `Option ${idx + 1}`);
          return `${idx + 1}. ${txt.slice(0, 500)}`;
        }).join("\n");

        const qStem = question || "[Question presented in image/media]";
        const qTypeHint = isMsq
          ? "This is a MULTIPLE-CHOICE question where ONE OR MORE options can be correct. Select ALL options that are correct."
          : "This is a SINGLE-CHOICE question where exactly ONE option is correct.";

        const prompt = (
          `Question:\n${qStem}\n\n` +
          `Options:\n${formattedOptions}\n\n` +
          `Instructions:\n${qTypeHint}\n` +
          "Carefully analyze each option step-by-step to eliminate distractors. " +
          "Output strictly valid JSON with 'reasoning' (1-2 concise sentences analyzing the options) " +
          "and 'selected_indices' (list of 1-based option numbers):\n" +
          '{"reasoning": "Option X is factually correct because...", "selected_indices": [1]}'
        );

        const systemPrompt = (
          "You are an expert, highly accurate test and quiz solver. " +
          "Analyze the question and select the exact correct multiple-choice option(s). " +
          "Always output strictly valid JSON."
        );

        const messages = [
          { role: "system", content: systemPrompt },
          { role: "user", content: prompt }
        ];

        let rawOutput = "";
        let engineUsed = "Cloudflare Workers AI";

        if (selectedModel) {
          ({ rawOutput, engineUsed } = await runSelectedModel(env, selectedModel, messages, imageBase64));
        } else {
          // Step 1: Attempt Primary Engine (Cloudflare Workers AI)
          try {
            rawOutput = await runWorkersAI(env, messages, imageBase64);
          } catch (cfErr) {
            console.warn("Workers AI primary failed, attempting Groq fallback:", cfErr.message);

            // Step 2: Fallback Engine (Groq Cloud)
            if (env.GROQ_API_KEY) {
              rawOutput = await runGroqAI(env.GROQ_API_KEY, messages, imageBase64);
              engineUsed = "Groq Cloud (Fallback)";
            } else {
              throw cfErr;
            }
          }
        }

        let parsed = extractJson(rawOutput);
        if (selectedModel && (!parsed || !Array.isArray(parsed.selected_indices) ||
            !parsed.selected_indices.length || parsed.selected_indices.some(index =>
              !Number.isInteger(index) || index < 1 || index > options.length))) {
          throw new Error("Selected model returned an invalid answer");
        }
        if (!parsed) {
          parsed = { reasoning: "Parsed from output", selected_indices: [1] };
        }
        parsed.provider = engineUsed;
        if (selectedModel) parsed.model = selectedModel;

        return jsonResponse(parsed);
      }

      // ─────────────────────────────────────────────────────────
      // Endpoint: /api/solve-fib (Fill-in-the-Blank)
      // ─────────────────────────────────────────────────────────
      if (url.pathname === "/api/solve-fib") {
        const body = await request.json();
        const selectedModel = body.model || "";
        if (selectedModel && !SELECTABLE_MODELS.has(selectedModel)) {
          return jsonResponse({ error: "Unsupported model" }, 400);
        }
        if (selectedModel && selectedModel !== QWEN_MODEL && body.image_base64) {
          return jsonResponse({ error: "Selected model supports text only" }, 400);
        }
        const question = (body.question || "").trim();
        const numBlanks = Math.max(1, Math.min(Number(body.num_blanks) || 1, 5));
        const imageBase64 = body.image_base64 || null;

        if (!question && !imageBase64) {
          return jsonResponse({ error: "Question text or image is required" }, 400);
        }

        const qStem = question || "[Question presented in image/media]";
        const instructions = numBlanks <= 1
          ? "Provide the exact single word, number, or short phrase that belongs in the blank.\n" +
            "Also provide 'plausible_wrong': a realistic human student mistake (never write 'incorrect').\n" +
            "Respond in JSON: {\"answer\": \"word\", \"plausible_wrong\": \"mistake\", \"reasoning\": \"brief\"}"
          : `Provide the missing words for EACH of the ${numBlanks} blanks in order.\n` +
            "Also provide 'plausible_wrongs': list of realistic student mistakes.\n" +
            "Respond in JSON: {\"answers\": [\"w1\", \"w2\"], \"plausible_wrongs\": [\"m1\", \"m2\"], \"reasoning\": \"brief\"}";

        const prompt = `Fill-in-the-blank Question:\n${qStem}\n\nInstructions:\n${instructions}`;
        const systemPrompt = (
          "You are an expert test solver. Complete fill-in-the-blank questions with accurate standard answers. " +
          "Never output the word 'incorrect'. Always respond strictly in valid JSON."
        );

        const messages = [
          { role: "system", content: systemPrompt },
          { role: "user", content: prompt }
        ];

        let rawOutput = "";
        let engineUsed = "Cloudflare Workers AI";

        if (selectedModel) {
          ({ rawOutput, engineUsed } = await runSelectedModel(env, selectedModel, messages, imageBase64));
        } else {
          try {
            rawOutput = await runWorkersAI(env, messages, imageBase64);
          } catch (cfErr) {
            console.warn("Workers AI FIB primary failed, attempting Groq fallback:", cfErr.message);
            if (env.GROQ_API_KEY) {
              rawOutput = await runGroqAI(env.GROQ_API_KEY, messages, imageBase64);
              engineUsed = "Groq Cloud (Fallback)";
            } else {
              throw cfErr;
            }
          }
        }

        let parsed = extractJson(rawOutput);
        if (selectedModel && (!parsed || !(parsed.answer || parsed.answers?.length))) {
          throw new Error("Selected model returned an invalid answer");
        }
        if (!parsed) {
          parsed = { answer: "answer", plausible_wrong: "answers", reasoning: "Fallback" };
        }
        parsed.provider = engineUsed;
        if (selectedModel) parsed.model = selectedModel;

        return jsonResponse(parsed);
      }

      return jsonResponse({ error: "Endpoint not found" }, 404);

    } catch (err) {
      return jsonResponse({ error: err.message || "Internal Gateway Error" }, 500);
    }
  }
};
