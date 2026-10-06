"""Browser worker for the native desktop UI. No console prompts or Qt widgets."""

import asyncio
from dataclasses import dataclass
import threading
from urllib.parse import urlparse, parse_qs
import uuid

import api
import config
from answer_db import AnswerDatabase, AnswerQuestion
from automation import (
    automate_test, scrape_results, _read_question_counter, _get_option_buttons,
    _extract_button_info, _extract_question_info, clear_highlights, highlight_answer,
)
from browser import is_port_open, launch_browser_with_debug
from desktop_engines import engine_catalog, probe, apply_engine, redact
from matching import _norm, _option_signature, rank_and_match_buttons, get_display_questions
from runtime_control import RuntimeControl, RunStopped, SessionChanged, ACTIVE_CANCELLATION
from session_binding import SessionBinding, SESSION_INFO_SCRIPT, is_game_url, session_route
from tabs import get_live_pages


def verified_manifest(questions, candidate):
    """Keep every game question; reject ambiguous or incompatible external rows."""
    records = list(getattr(candidate, "questions", {}).values())
    if not records and candidate:
        records = [AnswerQuestion("", text, answers)
                   for text, answers in get_display_questions(candidate)]
    used = set()
    result = AnswerDatabase()
    for question in questions:
        qid = str(question.get("_id") or question.get("id") or "")
        structure = question.get("structure") or {}
        query = structure.get("query") or {}
        text = api._clean_text(query.get("text", ""))
        images = api._media_urls(query.get("media"))
        options = [{"text": api._clean_text(option.get("text", "")),
                    "img_src": (api._media_urls(option.get("media")) or [""])[0]}
                   for option in structure.get("options", []) or [] if isinstance(option, dict)]
        kind = str(question.get("type") or structure.get("kind") or "").upper()
        exact = [i for i, record in enumerate(records) if record.qid == qid and qid and i not in used]
        candidates = exact or [
            i for i, record in enumerate(records) if i not in used and text and _norm(record.text) == _norm(text)
        ]
        compatible = []
        for index in candidates:
            record = records[index]
            if text and _norm(record.text) != _norm(text):
                continue
            if record.options and options and _option_signature(record.options) != _option_signature(options):
                continue
            if options and record.answers and kind not in ("BLANK", "FIB", "FITB"):
                if not all(rank_and_match_buttons(options, [answer], is_msq=False)[0]
                           for answer in record.answers):
                    continue
            compatible.append(index)
        record = records[compatible[0]] if len(compatible) == 1 else None
        if record:
            used.add(compatible[0])
        answers = list(record.answers) if record else []
        manual = bool((record and record.manual_required) or (kind == "OPEN" and not answers))
        result.add_question(text, answers, qid=qid, images=images, options=options,
                            manual_required=manual)
    return result


def game_identifier(value, selected_url):
    """Parse the visible PIN/link field without interpreting encrypted URLs as PINs."""
    clean = str(value or "").strip()
    if not clean:
        return "", ""
    if api.is_valid_game_pin(clean):
        return clean, ""
    if clean.startswith(("http://", "https://")):
        if not is_game_url(clean):
            raise ValueError("Enter a Wayground game PIN or game link. Put teacher quiz links in the answer-source field.")
        parsed = urlparse(clean)
        query = parse_qs(parsed.query)
        pin = next((query.get(key, [""])[0] for key in ("gc", "gameCode", "roomCode")
                    if query.get(key)), "")
        room_hash = query.get("roomHash", [""])[0]
        if pin and not api.is_valid_game_pin(pin):
            raise ValueError("The game link contains an invalid PIN.")
        if room_hash and not api.ROOM_HASH_REGEX.fullmatch(room_hash):
            raise ValueError("The game link contains an invalid room hash.")
        if pin or room_hash:
            return pin, room_hash
        path = parsed.path.rstrip("/")
        token = path.removeprefix("/join/") if path.startswith("/join/") else ""
        if "/" not in token and api.ROOM_HASH_REGEX.fullmatch(token):
            return "", token
        if session_route(clean) != session_route(selected_url):
            raise ValueError("That running-game link does not identify the selected tab.")
        # /join/game/<encrypted session> identifies the selected browser page,
        # but is not an API room hash. AI can operate directly on its question DOM.
        return "", ""
    if api.ROOM_HASH_REGEX.fullmatch(clean) and not clean.isdigit():
        return "", clean
    raise ValueError("Enter a valid game PIN or a Wayground game link.")


@dataclass
class PreparedGame:
    binding: SessionBinding
    database: AnswerDatabase
    name: str
    pin: str
    total: int
    source: str
    mode: str
    engine_id: str
    ready: bool
    question_ids: set
    current: int = 0


class DesktopBackend:
    def __init__(self, emit, *, port=9222):
        self.emit_callback = emit
        self.port = port
        self.engines = engine_catalog()
        self.default_model = config.AI_MODEL
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._thread_main, daemon=True, name="WaygroundBrowser")
        self.browser = None
        self.playwright = None
        self.pages = {}
        self.captured = {}
        self.selected = ""
        self.prepared = None
        self.control = None
        self.run_task = None
        self.operation = None
        self.watcher = None
        self.closed = False
        self.active_engine = "gateway"

    def start(self):
        self.thread.start()

    def _thread_main(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def emit(self, kind, **data):
        if not self.closed or kind == "closed":
            self.emit_callback({"type": kind, **data})

    def clean(self, message):
        text = redact(message)
        for engine in self.engines.values():
            if engine.key:
                text = text.replace(engine.key, "[redacted]")
        return text

    def request(self, command, **arguments):
        if not self.closed:
            self.loop.call_soon_threadsafe(self._schedule, command, arguments)

    def _schedule(self, command, arguments):
        if command in ("pause", "answer_now", "wrong", "settings"):
            self._controls(command, arguments)
            return
        if command in ("stop", "select", "shutdown"):
            if self.control:
                self.control.stop()
            if self.run_task and not self.run_task.done():
                self.run_task.cancel()
            if self.operation and not self.operation.done():
                cancellation = getattr(self.operation, "cancellation", None)
                if cancellation:
                    cancellation.set()
                self.operation.cancel()
        if command not in ("stop", "select", "shutdown", "open_tab") and self.operation and not self.operation.done():
            self.emit("error", message="An operation is already in progress.")
            return
        task = self.loop.create_task(self._execute(command, arguments))
        task.cancellation = threading.Event()
        if command != "open_tab":
            self.operation = task

    async def _execute(self, command, arguments):
        cancellation = getattr(asyncio.current_task(), "cancellation", threading.Event())
        token = ACTIVE_CANCELLATION.set(cancellation)
        busy = command in ("connect", "refresh", "prepare", "check_engine")
        if busy:
            self.emit("busy", busy=True, operation=command)
        try:
            handler = getattr(self, "_" + command)
            await handler(**arguments)
        except SessionChanged as exc:
            self.prepared = None
            self.emit("session_lost", message=self.clean(exc))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.emit("error", message=self.clean(exc), operation=command)
        finally:
            cancellation.set()
            ACTIVE_CANCELLATION.reset(token)
            if busy:
                self.emit("busy", busy=False, operation=command)

    def _controls(self, command, values):
        if not self.control:
            return
        if command == "pause":
            self.control.pause(values.get("paused", not self.control.paused))
        elif command == "answer_now":
            self.control.answer_now()
        elif command == "wrong":
            self.control.toggle_wrong()
        else:
            if "delay" in values:
                self.control.delay = max(0.0, float(values["delay"]))
            if "wrong_limit" in values:
                self.control.set_wrong_limit(values["wrong_limit"])
            if "highlight" in values:
                self.control.highlight = bool(values["highlight"])
                self.loop.create_task(self._update_highlights())

    async def _update_highlights(self):
        if not self.prepared or not self.control:
            return
        try:
            await self.prepared.binding.validate()
            page = self.prepared.binding.page
            await clear_highlights(page)
            if self.control.highlight and self.control.phase == "waiting" and self.control.verified:
                handles = await _get_option_buttons(page)
                options = [await _extract_button_info(button, idx=i) for i, button in enumerate(handles)]
                indices, _ = rank_and_match_buttons(options, self.control.correct_answers,
                                                     is_msq=len(self.control.correct_answers) > 1)
                for index in indices:
                    await highlight_answer(page, handles[index])
        except (Exception, RunStopped):
            pass

    async def _connect(self):
        from playwright.async_api import async_playwright
        if self.browser and self.browser.is_connected():
            await self._refresh()
            return
        if not await asyncio.to_thread(is_port_open, self.port):
            def launch():
                try:
                    return launch_browser_with_debug(self.port, interactive=False)
                except SystemExit:
                    raise RuntimeError("Install Microsoft Edge or Google Chrome, then connect again.") from None
            await asyncio.to_thread(launch)
        if not self.playwright:
            self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.browser.on("disconnected", self._disconnected)
        pages = await get_live_pages(self.browser)
        if not any(is_game_url(page.url) for page in pages):
            context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
            page = await context.new_page()
            await page.goto("https://wayground.com/join", wait_until="domcontentloaded")
        self.emit("browser", connected=True, message="Automator browser connected")
        await self._refresh()
        if not self.watcher:
            self.watcher = asyncio.create_task(self._watch_session())

    def _disconnected(self):
        if self.control:
            self.control.stop()
        if self.run_task and not self.run_task.done():
            self.run_task.cancel()
        self.prepared = None
        self.emit("browser", connected=False, message="Browser disconnected. Reconnect and select a test.")

    async def _capture_response(self, page_id, response):
        if "/play-api/" not in response.url:
            return
        try:
            payload = await response.json()
            room = payload.get("room") or payload.get("data", {}).get("room") or {}
            try:
                request = response.request.post_data_json or {}
            except Exception:
                request = {}
            room_hash = str(room.get("hash") or room.get("roomHash") or request.get("roomHash") or "")
            pin = str(room.get("code") or room.get("gameCode") or room.get("roomCode") or
                      request.get("roomCode") or request.get("gameCode") or "")
            previous = dict(self.captured.get(page_id, {}))
            if room_hash and api.ROOM_HASH_REGEX.fullmatch(room_hash):
                previous["hash"] = room_hash
            if pin and api.is_valid_game_pin(pin):
                previous["pin"] = pin
            if previous:
                self.captured[page_id] = previous
        except Exception:
            pass

    async def _refresh(self):
        if not self.browser or not self.browser.is_connected():
            raise RuntimeError("Connect the Automator browser first.")
        live = await get_live_pages(self.browser)
        previous = {id(page): page_id for page_id, page in self.pages.items()}
        self.pages = {}
        rows, answer_tabs = [], []
        for page in live:
            page_id = previous.get(id(page)) or uuid.uuid4().hex
            self.pages[page_id] = page
            if not previous.get(id(page)):
                page.on("response", lambda response, pid=page_id: self.loop.create_task(self._capture_response(pid, response)))
            try:
                title = await page.title() or "Wayground game"
            except Exception:
                continue
            host = (urlparse(page.url).hostname or "").lower()
            if host == "cheatnetwork.eu" or host.endswith(".cheatnetwork.eu"):
                answer_tabs.append({"id": page_id, "title": title, "url": page.url})
            if not is_game_url(page.url):
                continue
            info = await page.evaluate(SESSION_INFO_SCRIPT) or {}
            captured = self.captured.get(page_id, {})
            current, total = await _read_question_counter(page)
            visible_pin = info.get("pin") if info.get("pinSource") not in ("storage", "referrer") else ""
            rows.append({"id": page_id, "title": title, "pin": visible_pin or captured.get("pin") or "",
                         "total": total, "current": current, "url": page.url})
        self.emit("tabs", tabs=rows, answer_tabs=answer_tabs, selected=self.selected)

    async def _select(self, tab_id=""):
        if self.run_task and not self.run_task.done():
            await self._stop()
        self.selected = tab_id
        self.prepared = None
        self.emit("invalidated")

    async def _check_engine(self, engine_id, live=False):
        engine = self.engines[engine_id]
        self.emit("provider_check", id=engine_id, pending=True, live=live)
        ok, detail = await probe(engine)
        self.emit("provider_check", id=engine_id, available=ok, detail=detail, pending=False, live=live)
        if ok and live and self.control:
            self.control.queue_engine(engine)
            self.emit("status", message=f"{engine.label} will apply to the next AI request.")

    def _apply_engine(self, engine):
        apply_engine(engine, default_model=self.default_model)
        self.active_engine = engine.id
        self.emit("engine_active", id=engine.id, label=engine.label)

    async def _prepare(self, tab_id, mode="keys", engine_id="gateway", pin="", source_url="",
                       answer_tab_id="", cheatnetwork=True, quizit=False):
        if self.run_task and not self.run_task.done():
            raise RuntimeError("Stop the current test before preparing another one.")
        page = self.pages.get(tab_id)
        if not page or page.is_closed() or not is_game_url(page.url):
            raise RuntimeError("Refresh tabs and select an open Wayground game.")
        self.selected = tab_id
        self.prepared = None
        info = await page.evaluate(SESSION_INFO_SCRIPT) or {}
        captured = self.captured.get(tab_id, {})
        visible_pin = info.get("pin") if info.get("pinSource") not in ("storage", "referrer") else ""
        detected_pin = str(visible_pin or captured.get("pin") or "")
        supplied_pin, supplied_hash = game_identifier(pin, page.url)
        if supplied_pin and detected_pin and supplied_pin != detected_pin:
            raise ValueError("The entered PIN does not match the selected game tab.")
        target_pin = supplied_pin or detected_pin
        visible_hash = info.get("hash") if info.get("hashSource") != "storage" else ""
        detected_hash = str(visible_hash or captured.get("hash") or "")
        if supplied_hash and detected_hash and supplied_hash != detected_hash:
            raise ValueError("The entered game link does not match the selected game session.")
        room_hash = supplied_hash or detected_hash
        binding = await SessionBinding.create(page, pin=target_pin, room_hash=room_hash)
        current, page_total = await _read_question_counter(page)
        identifier = target_pin or room_hash
        if not identifier and mode == "keys":
            raise ValueError("Enter the game PIN for this tab, then check its answers.")
        snapshot = None
        if identifier:
            self.emit("status", message="Reading the selected game's questions…")
            try:
                snapshot = await asyncio.to_thread(api.fetch_game_snapshot, identifier)
            except Exception as exc:
                if mode == "keys":
                    raise RuntimeError(f"Could not read the selected game: {self.clean(exc)}") from None
                self.emit("log", message=f"Game manifest unavailable; AI will read the selected tab: {self.clean(exc)}")
        elif mode != "keys":
            self.emit("status", message="AI will read questions directly from the selected game tab.")
        await binding.validate(captured=self.captured.get(tab_id))
        snapshot = snapshot or {"questions": [], "name": "", "hash": room_hash, "pin": target_pin}
        snapshot_hash = str(snapshot.get("hash") or "")
        if detected_hash and snapshot_hash and detected_hash != snapshot_hash:
            raise ValueError("The entered PIN points to a different game session than the selected tab.")
        snapshot_pin = str(snapshot.get("pin") or "")
        if detected_pin and snapshot_pin and detected_pin != snapshot_pin:
            raise ValueError("The entered PIN does not match the selected game tab.")
        binding.room_hash = snapshot_hash or room_hash
        questions = snapshot.get("questions", [])
        title = snapshot.get("name") or await page.title() or "Wayground game"
        total = len(questions) or page_total
        if not total and mode == "keys":
            raise RuntimeError("Question count is unavailable. Join the game and check again.")
        if questions:
            live_question = await _extract_question_info(page)
            live_qid = str(live_question.get("qid") or "")
            known_ids = {str(question.get("_id") or question.get("id") or "") for question in questions}
            if live_qid and known_ids - {""} and live_qid not in known_ids:
                raise ValueError("The entered PIN's questions do not match the test already running in the selected tab.")
            if not live_qid and live_question.get("text") and not detected_pin and not detected_hash:
                handles = await _get_option_buttons(page)
                options = [await _extract_button_info(button, idx=index) for index, button in enumerate(handles)]
                manifest = verified_manifest(questions, None)
                compatible = [record for record in manifest.questions.values()
                              if _norm(record.text) == _norm(live_question["text"]) and
                              (not options or _option_signature(record.options) == _option_signature(options))]
                if not compatible:
                    raise ValueError("The entered PIN's questions do not match the test already running in the selected tab.")
        candidate, source = None, "No verified keys"
        # Disable the optional external bot unless the user explicitly selects it.
        api.set_allow_quizit_bot(bool(quizit))
        if mode != "ai" and questions:
            if source_url.strip():
                quiz_id = api.extract_quiz_id_from_url(source_url.strip())
                host = urlparse(source_url.strip()).hostname
                if host not in ("wayground.com", "www.wayground.com", "quizizz.com", "www.quizizz.com") or not api.is_valid_quiz_id(quiz_id):
                    raise ValueError("The answer-source URL must be a Wayground quiz page.")
                payload = await asyncio.to_thread(api._fetch_quiz_payload, quiz_id)
                candidate = api._verified_quiz_answers(questions, payload)
                source = "Wayground quiz URL (verified)"
                if not candidate:
                    raise ValueError("That source quiz does not match all questions in the selected game.")
            else:
                try:
                    candidate = await asyncio.to_thread(api.fetch_game_answers, identifier)
                    source = "Wayground Game / Quiz API"
                except Exception as exc:
                    self.emit("log", message=f"Direct lookup: {self.clean(exc)}")
            await binding.validate(captured=self.captured.get(tab_id))
            if not candidate and cheatnetwork:
                candidate, source = await self._cheatnetwork_keys(page, target_pin, answer_tab_id, questions)
            if not candidate and quizit:
                from quizit import fetch_quizit_browser_answers
                if target_pin:
                    candidate = await fetch_quizit_browser_answers(page.context, target_pin)
                    source = "Quizit Standard"
        database = verified_manifest(questions, candidate)
        records = list(database.questions.values())
        fixed = sum(bool(record.answers) for record in records)
        manual = sum(record.manual_required for record in records)
        complete = bool(questions) and fixed + manual == len(questions)
        ai_ok = False
        if mode != "keys":
            self.emit("status", message="Checking the selected AI with a test request…")
            ai_ok, detail = await probe(self.engines[engine_id])
            self.emit("provider_check", id=engine_id, available=ai_ok, detail=detail, pending=False, live=False)
            if ai_ok:
                self._apply_engine(self.engines[engine_id])
        await binding.validate(captured=self.captured.get(tab_id))
        ready = complete if mode == "keys" else ai_ok
        self.prepared = PreparedGame(binding, database, title, target_pin, total, source or "No verified keys",
                                     mode, engine_id, ready,
                                     {str(question.get("_id") or question.get("id")) for question in questions
                                      if question.get("_id") or question.get("id")}, current=current)
        issue = ""
        if mode == "keys" and not complete:
            issue = f"{fixed} fixed keys and {manual} written responses matched {total} questions. Complete keys are required in this mode."
        elif mode != "keys" and not ai_ok:
            issue = "The selected AI is unavailable. Choose another engine or use verified keys only."
        elif mode == "auto" and not complete:
            issue = "Missing keys will be solved by AI. Predictions may be incorrect."
        elif mode == "ai" and not total:
            issue = "AI will read the current test tab. Progress will update when its question count appears."
        self.emit("prepared", name=title, pin=target_pin, total=total, current=current,
                  key_count=fixed, manual_count=manual, complete=complete, can_start=ready,
                  mode=mode, engine_id=engine_id, source=self.prepared.source, issue=issue,
                  questions=[{"question": record.text, "answers": record.answers,
                              "manual": record.manual_required} for record in records])

    async def _cheatnetwork_keys(self, page, pin, answer_tab_id, questions):
        from scraper import scrape_answers, read_cheatnetwork_state
        from answer_tabs import is_cheatnetwork_page
        source_page = self.pages.get(answer_tab_id) if answer_tab_id else None
        if source_page and not is_cheatnetwork_page(source_page):
            raise ValueError("Select a CheatNetwork answer tab.")
        if not source_page:
            for candidate in await get_live_pages(self.browser):
                if is_cheatnetwork_page(candidate):
                    state = await read_cheatnetwork_state(candidate)
                    if state.get("status") == "ready":
                        keys = await scrape_answers(candidate)
                        manifest = verified_manifest(questions, keys)
                        records = list(manifest.questions.values())
                        if records and all(record.answers or record.manual_required for record in records):
                            return keys, "CheatNetwork (existing tab)"
        if not source_page:
            source_page = await page.context.new_page()
            await source_page.goto(config.ANSWERS_URL, wait_until="domcontentloaded")
        self.emit("status", message="Waiting for CheatNetwork. Its page will not be refreshed.")
        keys = await scrape_answers(source_page, quiz_input=f"https://wayground.com/join?gc={pin}" if pin else None)
        if not keys:
            self.emit("browser_action", message="Sign in or finish downloading answers in CheatNetwork, then check again.")
        return keys, "CheatNetwork"

    async def _binding_guard(self):
        if not self.prepared or not self.browser or not self.browser.is_connected():
            raise SessionChanged("The selected test or browser is no longer connected.")
        await self.prepared.binding.validate(captured=self.captured.get(self.selected))
        captured = self.captured.get(self.selected, {})
        if captured.get("pin") and self.prepared.binding.pin and captured["pin"] != self.prepared.binding.pin:
            raise SessionChanged("The selected tab entered a different game PIN. Prepare the new test.")
        if captured.get("hash") and self.prepared.binding.room_hash and captured["hash"] != self.prepared.binding.room_hash:
            raise SessionChanged("The selected tab entered a different game session. Prepare the new test.")
        if self.control and self.run_task and not self.run_task.done() and self.prepared.question_ids:
            current = await _extract_question_info(self.prepared.binding.page)
            qid = str(current.get("qid") or "")
            if qid and qid not in self.prepared.question_ids:
                raise SessionChanged("This question is outside the prepared test. Check its answers again.")

    async def _watch_session(self):
        try:
            while not self.closed:
                if self.prepared:
                    try:
                        await self._binding_guard()
                    except (SessionChanged, Exception) as exc:
                        if self.control:
                            self.control.stop()
                        if self.run_task and not self.run_task.done():
                            self.run_task.cancel()
                        self.prepared = None
                        self.emit("session_lost", message=self.clean(exc))
                await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            pass

    async def _start_run(self, delay=config.MIN_THINK_SECONDS, wrong_limit=0, highlight=True):
        if not self.prepared or not self.prepared.ready:
            raise RuntimeError("Select and prepare the test before starting.")
        if self.run_task and not self.run_task.done():
            raise RuntimeError("Automation is already running.")
        await self._binding_guard()
        self.control = RuntimeControl(self.emit_callback, guard=self._binding_guard, delay=delay,
                                      wrong_limit=wrong_limit, highlight=highlight,
                                      apply_engine=self._apply_engine)
        game = self.prepared
        current, total = await _read_question_counter(game.binding.page)
        game.current = current or game.current
        if total:
            game.total = total
        self.emit("started", name=game.name, pin=game.pin, total=game.total, current=game.current,
                  mode=game.mode, engine_id=game.engine_id)
        self.run_task = asyncio.create_task(self._run(game, self.control))

    async def _run(self, game, control):
        token = ACTIVE_CANCELLATION.set(control.cancellation)
        complete = False
        try:
            complete = await automate_test(
                game.binding.page, game.database, expected_total=game.total,
                use_ai=game.mode != "keys", ai_only=game.mode == "ai", control=control,
            )
            if complete:
                stats = await scrape_results(game.binding.page, timeout=3)
                if stats:
                    self.emit("results", stats=stats)
        except SessionChanged as exc:
            self.prepared = None
            self.emit("session_lost", message=self.clean(exc))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.emit("attention", message=self.clean(exc))
        finally:
            control.phase = "finished"
            control.cancellation.set()
            ACTIVE_CANCELLATION.reset(token)
            if not game.binding.page.is_closed():
                await clear_highlights(game.binding.page)
            self.emit("finished", complete=bool(complete))

    async def _stop(self):
        if self.run_task:
            try:
                await self.run_task
            except asyncio.CancelledError:
                pass
        self.prepared = None
        self.emit("invalidated")
        self.emit("finished", complete=False)

    async def _open_tab(self):
        page = self.prepared.binding.page if self.prepared else self.pages.get(self.selected)
        if page and not page.is_closed():
            await page.bring_to_front()

    async def _shutdown(self):
        await self._stop()
        if self.watcher:
            self.watcher.cancel()
        if self.playwright:
            await self.playwright.stop()  # Disconnects CDP; leaves the user's browser open.
        self.closed = True
        self.emit("closed")
        self.loop.call_soon(self.loop.stop)
