"""Performance stage definitions.

The performance is a sequence of STAGES the performer walks through from the
/admin console. Each stage is plain data — edit this list to shape the show,
no other code changes needed. On every stage change the server broadcasts
`stage_update` to phones AND TouchDesigner (raw /ws), so TD can switch scenes
on `data.stage`.

Fields per stage:
  id              short unique slug (what TD switches on)
  label           button text in the admin console
  scroll_enabled  do audience swipes count toward the collective threshold?
  vibrate_ms      vibrate every phone for N ms when the stage begins (0 = off).
                  NOTE: works on Android Chrome; iOS Safari ignores it.
  screen          what the audience sees:
                    {"mode": "text",  "text": "..."}            centered text on white
                    {"mode": "image", "image": "static/..."}    full-screen image
                    {"mode": "black"}                            black screen
                    {"mode": "white"}                            blank white screen
                    {"mode": "intro"}                            per-person gather
                        screen: "You are the Nth person in my dream…" where N is
                        the stable join-order label the server assigned that
                        phone when it opened the page (see main.py person_number).
  poll            optional {"question": "...", "options": ["A", "B"]} —
                  entering the stage starts this poll (phones show the two
                  buttons, votes stream live to the admin console). Leaving
                  the stage ends it.

These are placeholders — refine ids/labels/content as the show script firms up.
"""

STAGES = [
    {
        # STEP 1 — projector shows the QR code, audience opens the page and
        # waits. Each phone shows its own "you are the Nth person" label.
        "id": "intro",
        "label": "1 · Intro / Gather (QR up)",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "intro"},
    },
    {
        # STEP 2 — same hold as the intro (scrolling off), but every phone goes
        # pure white. TD gets the stage_update too (state number below).
        "id": "lost",
        "label": "2 · I Got Lost",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "white"},
    },
    {
        "id": "idle",
        "label": "Idle / Pre-show",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "ScrollMe"},
    },
    {
        "id": "scroll",
        "label": "Scroll",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
    },
    {
        "id": "poll",
        "label": "Poll",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "text", "text": ""},
        "poll": {"question": "Keep scrolling?", "options": ["Yes", "No"]},
    },
    {
        "id": "image",
        "label": "Image",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "image", "image": "static/images/1.jpg"},
    },
    {
        "id": "black",
        "label": "Blackout",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "black"},
    },
    {
        "id": "end",
        "label": "End",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Thank you"},
    },
]
