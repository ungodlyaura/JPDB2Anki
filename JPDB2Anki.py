# ---------------------------
# Presets (fill to skip prompts)
# ---------------------------
PRESET_API_KEY = ""         # Find your API key at https://jpdb.io/settings/ very bottom.
PRESET_DECK_ID = ""         # ID of the deck, do not confuse with deck number in normal selection.
PRESET_MODE = ""            # "1" or "2" or "basic" / "advanced"
PRESET_OUTPUT_FILE = "anki_import.csv" # Found in .py script directory

# Advanced options presets (used if PRESET_MODE is "advanced")
PRESET_MIN_OCCURRENCES = None         # int >=0
PRESET_MAX_DAYS_UNTIL_DUE = None      # int days or None
PRESET_MAX_CARD_LEVEL = None          # int or None
PRESET_INCLUDE_BANISHED = None        # bool
PRESET_INCLUDE_NEVER_FORGET = True    # bool
PRESET_MAX_FREQUENCY_RANK = None      # int or None
PRESET_MAX_RESULTS = None             # int, 0 = all
# ---------------------------

"""

#--------------------------------
# JPDB -> Anki : Vocabulary Exporter
# Author: ungodlyaura
# Description: Export vocabulary from a JPDB deck to an Anki-compatible CSV file.
# Usage: with python run JPDB2Anki.py
# Note: Fill in presets at the top of the script to skip prompts. Results are ordered by occurrences in deck (for in-built decks).
# Date: 2025-12-10
#--------------------------------

MIT License
Copyright (c) 2025 ungodlyaura

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import requests
import sys
import csv
import json
import time
from datetime import datetime, timezone, timedelta


def send_post(url: str, headers: dict, payload: dict, max_retries: int = 3, backoff_base: float = 1.0):
    """Send POST with retries on 429 and good error messages. Returns parsed JSON on success."""
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
        except requests.exceptions.RequestException as e:
            print(f"Network error when POST {url}: {e}")
            if attempt >= max_retries:
                raise
            time.sleep(backoff_base * attempt)
            continue

        try:
            data = r.json()
        except Exception:
            data = None

        if r.status_code == 200:
            return data
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", 1))
            wait = backoff_base * attempt + retry_after
            print(f"Rate limited (429). Waiting {wait:.1f}s before retry ({attempt}/{max_retries})...")
            time.sleep(wait)
            continue
        if r.status_code == 403:
            msg = data.get("error_message") if isinstance(data, dict) and "error_message" in data else "Forbidden (403) - check API key"
            raise RuntimeError(msg)
        if r.status_code == 400:
            msg = data.get("error_message") if isinstance(data, dict) and "error_message" in data else "Bad request (400)"
            raise RuntimeError(msg)

        msg = f"HTTP {r.status_code}"
        if isinstance(data, dict) and "error_message" in data:
            msg += f": {data['error_message']}"
        raise RuntimeError(msg)

    raise RuntimeError("Exceeded maximum retries")


def ping_api_key(api_key: str) -> bool:
    url = "https://jpdb.io/api/v1/ping"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    try:
        data = send_post(url, headers, {})
    except Exception as e:
        print(f"Ping failed: {e}")
        return False

    if isinstance(data, dict) and data.get("error"):
        print("API rejected key:", data.get("error_message", data.get("error")))
        return False

    print("API Verified")
    return True


def select_deck(api_key: str, preset_deck_id: str = "") -> str:
    url = "https://jpdb.io/api/v1/list-user-decks"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    body = {
        "fields": [
            "id",
            "name",
            "vocabulary_count",
            "word_count",
            "vocabulary_known_coverage",
            "vocabulary_in_progress_coverage",
        ]
    }

    try:
        data = send_post(url, headers, body)
    except Exception as e:
        print(f"Failed to fetch decks: {e}")
        sys.exit(1)

    if not isinstance(data, dict) or "decks" not in data:
        print("Unexpected decks response.")
        sys.exit(1)

    decks = data["decks"]

    if preset_deck_id:
        for d in decks:
            if len(d) > 0 and str(d[0]) == str(preset_deck_id):
                print(f"Using preset deck id {preset_deck_id}")
                return str(preset_deck_id)
        print("Preset deck id not found in your account. Falling back to interactive selection.")

    if not decks:
        print("No user decks found.")
        sys.exit(1)

    print("\nYour decks:\n")
    for idx, deck in enumerate(decks, start=1):
        deck_id = deck[0] if len(deck) > 0 else "N/A"
        deck_name = deck[1] if len(deck) > 1 else "Unknown"
        vocab_count = deck[2] if len(deck) > 2 else 0
        word_count = deck[3] if len(deck) > 3 else 0
        try:
            known_coverage = float(deck[4]) if len(deck) > 4 and deck[4] is not None else 0.0
        except Exception:
            known_coverage = 0.0
        try:
            in_progress_coverage = float(deck[5]) if len(deck) > 5 and deck[5] is not None else 0.0
        except Exception:
            in_progress_coverage = 0.0
        is_built_in = deck[6] if len(deck) > 6 else False

        print(f"{idx}: {deck_name}")
        print(f"  id={deck_id}  vocabulary count: {vocab_count} | word count: {word_count} | "
              f"known_coverage: {known_coverage:.1f}% | in_progress: {in_progress_coverage:.1f}% | built-in: {is_built_in}")

    while True:
        choice = input("Please select deck number: ").strip()
        if not choice:
            print("Selection cannot be empty.")
            continue
        try:
            num = int(choice)
            if 1 <= num <= len(decks):
                return str(decks[num - 1][0])
            print(f"Invalid number. Enter 1..{len(decks)}.")
        except ValueError:
            print("Invalid input. Enter a number.")



def get_deck_vocabulary(deck_id: str, api_key: str) -> list:
    url = "https://jpdb.io/api/v1/deck/list-vocabulary"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    body = {"id": int(deck_id), "fetch_occurences": True}

    try:
        data = send_post(url, headers, body)
    except Exception as e:
        print(f"Failed to fetch deck vocabulary: {e}")
        sys.exit(1)

    raw_vocab = data.get("vocabulary", [])
    raw_occ = data.get("occurences", [])

    combined = []
    for i, entry in enumerate(raw_vocab):
        vid = entry[0] if len(entry) > 0 else None
        sid = entry[1] if len(entry) > 1 else None
        occ = raw_occ[i] if i < len(raw_occ) else None
        combined.append({"vid": vid, "sid": sid, "occurrences": occ})

    return combined



def lookup_vocabulary(entries: list, api_key: str, batch_size: int = 50) -> list:
    API_URL = "https://jpdb.io/api/v1/lookup-vocabulary"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    occ_map = {}
    lookup_pairs = []
    for e in entries:
        vid = e.get("vid") if isinstance(e, dict) else None
        sid = e.get("sid") if isinstance(e, dict) else None
        occ = e.get("occurrences") if isinstance(e, dict) else None
        if vid is None or sid is None:
            continue
        occ_map[vid] = occ
        lookup_pairs.append([vid, sid])

    if not lookup_pairs:
        return []

    parsed = []
    fields = [
        "spelling", "reading", "frequency_rank",
        "meanings", "card_level", "card_state"
    ]

    for i in range(0, len(lookup_pairs), batch_size):
        batch = lookup_pairs[i:i + batch_size]
        payload = {"list": batch, "fields": fields}
        try:
            data = send_post(API_URL, headers, payload)
        except Exception as e:
            print(f"Lookup vocabulary failed: {e}")
            sys.exit(1)
        rows = data.get("vocabulary_info", [])
        for row_idx, row in enumerate(rows):
            if row is None:
                continue
            item = {}
            for idx, name in enumerate(fields):
                item[name] = row[idx] if idx < len(row) else None
            vid = batch[row_idx][0] if row_idx < len(batch) else None
            item["vid"] = vid
            item["occurrences"] = occ_map.get(vid, 0)
            parsed.append(item)

    return parsed



def ask_mode_and_options(preset_mode: str = ""):
    mode = "basic"
    if preset_mode:
        pm = preset_mode.strip()
        if pm in ("1", "basic"):
            mode = "basic"
        elif pm in ("2", "advanced"):
            mode = "advanced"
    else:
        ans = input("Choose mode - '1' (basic) or '2' (advanced) (default: basic): ").strip()
        if ans == "2":
            mode = "advanced"
        else:
            mode = "basic"

    options = {
        "mode": mode,
        "min_occurrences": 0,
        "max_days_until_due": None,
        "max_card_level": None,
        "include_banished": False,
        "include_never_forget": False,
        "max_frequency_rank": None,
        "max_results": 0
    }

    if mode == "advanced":
        options["min_occurrences"] = PRESET_MIN_OCCURRENCES
        options["max_days_until_due"] = PRESET_MAX_DAYS_UNTIL_DUE
        options["max_card_level"] = PRESET_MAX_CARD_LEVEL
        options["include_banished"] = PRESET_INCLUDE_BANISHED
        options["include_never_forget"] = PRESET_INCLUDE_NEVER_FORGET
        options["max_frequency_rank"] = PRESET_MAX_FREQUENCY_RANK
        options["max_results"] = PRESET_MAX_RESULTS

        if options["min_occurrences"] is None:
            while True:
                v = input("Minimum occurrences in deck [0]: ").strip()
                if v == "":
                    options["min_occurrences"] = 0
                    break
                try:
                    n = int(v)
                    options["min_occurrences"] = max(0, n)
                    break
                except ValueError:
                    print("Enter integer or leave blank.")

        if options["max_days_until_due"] is None:
            while True:
                v = input("Maximum days until due (blank = no limit): ").strip()
                if v == "":
                    options["max_days_until_due"] = None
                    break
                try:
                    n = int(v)
                    options["max_days_until_due"] = max(0, n)
                    break
                except ValueError:
                    print("Enter integer or leave blank.")
        elif options["max_days_until_due"] == 0:
            options["max_days_until_due"] = None

        if options["max_card_level"] is None:
            while True:
                v = input("Maximum card_level (blank = no limit): ").strip()
                if v == "":
                    options["max_card_level"] = None
                    break
                try:
                    n = int(v)
                    options["max_card_level"] = max(0, n)
                    break
                except ValueError:
                    print("Enter integer or leave blank.")
        elif options["max_card_level"] == 0:
            options["max_card_level"] = None

        if PRESET_INCLUDE_BANISHED is None:
            while True:
                v = input("Include banished cards? (Y/N) [N]: ").strip().lower()
                if v == "":
                    options["include_banished"] = False
                    break
                if v in ("y", "yes"):
                    options["include_banished"] = True
                    break
                if v in ("n", "no"):
                    options["include_banished"] = False
                    break
                print("Enter y or n, or press Enter for default N.")

        if PRESET_INCLUDE_NEVER_FORGET is None:
            while True:
                v = input("Include never_forget cards? (Y/N) [N]: ").strip().lower()
                if v == "":
                    options["include_never_forget"] = False
                    break
                if v in ("y", "yes"):
                    options["include_never_forget"] = True
                    break
                if v in ("n", "no"):
                    options["include_never_forget"] = False
                    break
                print("Enter y or n, or press Enter for default N.")

        if options["max_frequency_rank"] is None:
            while True:
                v = input("Maximum word frequency rank (blank = no limit; lower = more common): ").strip()
                if v == "":
                    options["max_frequency_rank"] = None
                    break
                try:
                    n = int(v)
                    options["max_frequency_rank"] = max(0, n)
                    break
                except ValueError:
                    print("Enter integer or leave blank.")
        elif options["max_frequency_rank"] == 0:
            options["max_frequency_rank"] = None

        if options["max_results"] is None:
            while True:
                v = input("Max results to import (0 = all) [0]: ").strip()
                if v == "":
                    options["max_results"] = 0
                    break
                try:
                    n = int(v)
                    options["max_results"] = max(0, n)
                    break
                except ValueError:
                    print("Enter integer or leave blank.")
    return options



def apply_filters(parsed_vocab: list, options: dict):
    """
    options keys:
      - min_occurrences (int)
      - max_days_until_due (int days) or None
      - max_card_level (int) or None
      - include_banished (bool)
      - include_never_forget (bool)
      - max_frequency_rank (int) or None
      - max_results (int, 0 = unlimited)
    """
    if not parsed_vocab:
        return []

    min_occ = options.get("min_occurrences", 0)
    max_days = options.get("max_days_until_due")
    max_card_level = options.get("max_card_level")
    include_banished = options.get("include_banished", False)
    include_never_forget = options.get("include_never_forget", False)
    max_freq = options.get("max_frequency_rank")
    max_results = options.get("max_results", 0)

    now_ts = int(time.time())
    filtered = []

    for item in parsed_vocab:
        occ = item.get("occurrences")
        if occ is None:
            occ_val = None
        else:
            try:
                occ_val = int(occ)
            except Exception:
                occ_val = None
        if occ_val is not None and occ_val < min_occ:
            continue


        if max_days is not None:
            due_at = item.get("due_at")
            if due_at is None:
                due_at_int = now_ts
            else:
                try:
                    due_at_int = int(due_at)
                except Exception:
                    continue
            max_due_ts = now_ts + (int(max_days) * 86400)
            if due_at_int > max_due_ts:
                continue


        if max_card_level is not None:
            cl = item.get("card_level")
            try:
                cl_val = int(cl) if cl is not None else None
            except Exception:
                cl_val = None
            if cl_val is None:
                pass
            else:
                if cl_val > max_card_level:
                    continue

        states = item.get("card_state") or []
        state_list = []
        if isinstance(states, list):
            for s in states:
                try:
                    state_list.append(str(s))
                except Exception:
                    pass
        elif isinstance(states, str):
            state_list = [states]

        if any(s in state_list for s in ("suspended", "blacklisted", "banished")) and not include_banished:
            continue
        if ("never-forget" in state_list) and not include_never_forget:
            continue

        freq = item.get("frequency_rank")
        if max_freq is not None:
            try:
                freq_val = int(freq) if freq is not None else None
            except Exception:
                freq_val = None
            if freq_val is None or freq_val > max_freq:
                continue

        filtered.append(item)
        if max_results and len(filtered) >= max_results:
            break
    print(filtered)
    return filtered


def export_anki_csv(vocab_info: list, filename: str = "anki_import.csv"):
    with open(filename, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Expression", "Reading", "Meaning"])
        for item in vocab_info:
            expr = item.get("spelling") or ""
            reading = item.get("reading") or ""
            meanings = item.get("meanings") or []
            if isinstance(meanings, list):
                meaning_text = "; ".join(meanings)
            else:
                meaning_text = str(meanings) if meanings is not None else ""
            writer.writerow([expr, reading, meaning_text])
    print(f"Anki CSV saved to {filename}")


def main():
    try:
        api_key = PRESET_API_KEY.strip() if PRESET_API_KEY else input("Enter your JPDB API Key: ").strip()
        if not api_key:
            print("API key required.")
            sys.exit(1)

        if not ping_api_key(api_key):
            print("API key validation failed.")
            sys.exit(1)

        opts = ask_mode_and_options(PRESET_MODE)

        deck_id = PRESET_DECK_ID.strip() if PRESET_DECK_ID else select_deck(api_key)
        if not deck_id:
            print("No deck selected.")
            sys.exit(1)

        print(f"Selected Deck ID: {deck_id}")

        vocab_list = get_deck_vocabulary(deck_id, api_key)
        if not vocab_list:
            print("No vocabulary in deck.")
            sys.exit(0)

        detailed = lookup_vocabulary(vocab_list, api_key)
        if not detailed:
            print("No detailed vocabulary returned.")
            sys.exit(0)

        
        filtered = apply_filters(detailed, opts)

        filtered.sort(key=lambda x: x.get("occurrences") or 0, reverse=True)


        print(f"\nPrepared {len(filtered)} cards for export.")

        out_file = PRESET_OUTPUT_FILE or input(f"Output CSV filename (default {PRESET_OUTPUT_FILE}): ").strip() or PRESET_OUTPUT_FILE
        export_anki_csv(filtered, filename=out_file)

    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()

