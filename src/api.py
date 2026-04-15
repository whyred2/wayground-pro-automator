"""
Wayground Direct API: network interception to capture quiz_id and fetch answers.
"""

import asyncio
import urllib.request
import json
import re
import html

from ui import log_info

# ─── Shared state for network interception ─────────────────────
_quiz_id_event = asyncio.Event()
_captured_quiz_id = None


async def intercept_response(response):
    """Network listener to catch Wayground's /join response and extract quiz _id."""
    global _captured_quiz_id
    if _quiz_id_event.is_set():
        return  # Already found — stop processing
    
    # Check if this might be our target API
    if "join" in (response.url or "") and response.request.method in ["POST", "GET"] and response.status == 200:
        try:
            body = await response.json()
            # Recursively find _id in quizInfo
            def find_id(d):
                if isinstance(d, dict):
                    if "quizInfo" in d and isinstance(d["quizInfo"], dict) and "_id" in d["quizInfo"]:
                        return d["quizInfo"]["_id"]
                    for v in d.values():
                        res = find_id(v)
                        if res: return res
                elif isinstance(d, list):
                    for item in d:
                        res = find_id(item)
                        if res: return res
                return None
                
            quiz_id = find_id(body)
            if quiz_id:
                # We only log on true success to avoid spamming the console 
                # before the user even presses Enter.
                print()  # Ensure we start on a new line (input() has no trailing \n)
                log_info(f"✅ Extracted quiz_id: {quiz_id}")
                _captured_quiz_id = quiz_id
                _quiz_id_event.set()
        except Exception:
            pass


def fetch_api_answers(quiz_id: str) -> dict[str, list[str]]:
    """
    Fetch raw quiz data from Wayground API and compile answers_db.
    """
    url = f"https://wayground.com/_quizserver/main/v2/quiz/{quiz_id}?convertQuestions=false&includeFsFeatures=true&sanitize=read&questionMetadata=true&includeUserHydratedVariants=true"
    
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}")
            data = json.loads(response.read().decode())
    except Exception as e:
        raise Exception(f"API fetch failed: {e}")
        
    quiz_data = data.get("data", {}).get("quiz", {})
    info_data = quiz_data.get("info", {})
    if not info_data:
        raise Exception("Invalid API response format (missing 'info')")
        
    answers_db = {}
    
    questions = info_data.get("questions", [])
    for q in questions:
        q_struct = q.get("structure", {})
        q_text_raw = q_struct.get("query", {}).get("text", "")
        if q_text_raw is None:
            continue
        q_text = html.unescape(re.sub('<[^<]+?>', '', q_text_raw)).strip()
        
        options_raw = q_struct.get("options", [])
        
        ans_raw = q_struct.get("answer")
        ans_indices = []
        if isinstance(ans_raw, int):
            ans_indices = [ans_raw]
        elif isinstance(ans_raw, list):
            ans_indices = ans_raw
            
        correct_texts = []
        for idx in ans_indices:
            try:
                idx = int(idx)
            except ValueError:
                continue
                
            if 0 <= idx < len(options_raw):
                opt = options_raw[idx]
                opt_text_raw = opt.get("text", "")
                if opt_text_raw is not None:
                    opt_text = html.unescape(re.sub('<[^<]+?>', '', opt_text_raw)).strip()
                    if opt_text:
                        correct_texts.append(opt_text)
                    
        if q_text and correct_texts:
            if q_text not in answers_db:
                answers_db[q_text] = []
            for text in correct_texts:
                if text not in answers_db[q_text]:
                    answers_db[q_text].append(text)
            
    return answers_db
