# Wayground AI Gateway (Cloudflare Worker — Smart Hybrid)

Интеллектуальный шлюз между клиентом `Wayground Pro Automator` (`.exe`) и нейросетями.

## 🧠 Архитектура "Умный гибрид":
1. **Основной движок (Primary):** **Cloudflare Workers AI** (`@cf/meta/llama-3.3-70b-instruct`).
   - Бесплатно 10 000 Neurons в день прямо из коробки в Cloudflare.
   - Не требует никаких внешних API-ключей.
   - Поддержка распознавания картинок через `@cf/meta/llama-3.2-11b-vision-instruct`.
2. **Резервный движок (Fallback):** **Groq Cloud** (`qwen/qwen3.8-27b`).
   - Если дневной лимит Workers AI исчерпан или сервис временно недоступен — запрос мгновенно и прозрачно для пользователя перенаправляется на резервный Groq через секрет `GROQ_API_KEY`.
3. **Защита:**
   - Rate Limiting по IP (до 30 запросов в минуту).
   - Узкие эндпоинты `/api/solve` и `/api/solve-fib` (нельзя использовать для посторонних промптов).

---

## 🚀 Обновление и деплой:

Перейдите в терминале в папку `cloudflare-worker` и выполните:

```bash
cd cloudflare-worker
npx wrangler deploy
```

Всё! Cloudflare автоматически применит биндинг `[ai]` и опубликует обновленный гибридный шлюз.
