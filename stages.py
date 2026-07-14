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
                    {"mode": "slideshow", "images": "auto"|[...],
                     "interval_ms": N, "overlay": "..."}         cycling images
                        Loops through images every interval_ms with overlay text
                        on top. "images": "auto" is enumerated live from
                        static/images/ (server-side), so files can be swapped
                        freely. Pair with a "finale" (below) to end on a swipe.
  finale          optional {"text": "...", "sound": "auto"|"static/...",
                  "loop": bool} — used with a slideshow stage: a single swipe by
                  any phone ends THAT phone's show — black screen + text, and the
                  sound plays (looped). Terminal on the client: nothing changes
                  after, the sound just keeps going. "sound": "auto" is taken
                  from static/sound/. Audio needs the swipe (a user gesture) to
                  start, which is why it's the swipe that triggers it.
  poll            optional {"question": "...", "options": ["A", "B"]} —
                  entering the stage starts this poll (phones show the two
                  buttons, votes stream live to the admin console). Leaving
                  the stage ends it. Optional "responses": ["...", "..."] gives
                  each voter a personal message (one per option) that replaces
                  the poll on *their* screen the instant they vote.
  scroll_feedback optional {"waiting_text": "...{n}...", "vibrate_ms": N} on a
                  collective (non-solo) scroll stage. After a phone swipes it
                  buzzes and shows waiting_text (with {n} replaced by how many
                  MORE swipes the room still needs), refreshed live as others
                  swipe, until the reel advances — then it resets to the stage's
                  normal screen. Non-swipers are unaffected. See main.py
                  emit_scroll_feedback().
  threshold_from_poll
                  optional {"stage": "<poll stage id>", "option": <int>} —
                  makes this (collective, scroll_enabled) stage's swipe
                  threshold DYNAMIC: instead of the fixed config percentage,
                  the bar becomes the share of the online audience who picked
                  that option in the named earlier poll. E.g. stage 6 sets
                  {"stage": "poll2", "option": 0} so the room must collectively
                  out-swipe the fraction who voted "poor" (Yes = option 0) to
                  advance the reel. The poll's final tally is snapshotted when
                  that poll ends (main.py poll_results), so it survives into
                  this later stage. See main.py collective_threshold().
  solo            optional {"chosen_text", "result_text", "not_chosen_text",
                  "result_hold_ms"} — turns this stage into ONE-AT-A-TIME
                  scrolling instead of the collective threshold: the server
                  randomly picks one online phone as "chosen"; only that
                  phone's swipe advances the reel. Chosen phone shows
                  chosen_text (green) then, after it swipes, result_text
                  (still green) for result_hold_ms, then a new phone is
                  chosen. Everyone else sees not_chosen_text (white) the whole
                  time. This is a separate mechanic from `scroll_enabled` +
                  the audience-percentage threshold, which stays available
                  (unchanged) for any stage that omits "solo" — see main.py
                  swipe() for how the two modes are kept independent.

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
        # STEP 3 — first audience poll. Entering the stage buzzes every phone
        # briefly and shows the two-option vote; results stream live to /admin.
        # Question (translated from the Farsi «الان احساس گم شدگی میکنی؟»).
        "id": "poll1",
        "label": "3 · Poll 1 — feeling lost?",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "white"},
        "poll": {
            "question": "Do you feel lost right now?",
            "options": ["Yes", "No"],
            # Personal reply shown to each voter after they answer (Yes / No).
            "responses": [
                "you feel me",
                "Others in this room feel just like you.\nYou are not alone among the lost creatures here.",
            ],
        },
    },
    {
        # STEP 4 — one-at-a-time scrolling. A single random phone is "chosen"
        # at any moment and only its swipe advances the reel; everyone else
        # just watches. After the chosen phone swipes it holds a reward line
        # for result_hold_ms, then a new phone is chosen and the loop
        # continues. The performer can still force a reel change early with
        # "Next reel now" in admin — that's a separate, unaffected mechanic
        # (main.py manual_next_reel) that pulses every phone regardless of
        # who's chosen.
        "id": "scroll1",
        "label": "4 · Scroll 1 (one at a time)",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "white"},
        "solo": {
            "chosen_text": "You are the chosen one.\nScroll for us.",
            # Paraphrase of "I know what I feel, get this dopamine".
            "result_text": "I know exactly what it feels like — this dopamine hit is mine.",
            "not_chosen_text": "You are not the selected one.",
            "result_hold_ms": 4000,
        },
    },
    {
        # STEP 5 — second audience poll.
        "id": "poll2",
        "label": "5 · Poll 2 — are you poor?",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "white"},
        "poll": {
            "question": "Are you poor?",
            "options": ["Yes", "No"],
            # Personal reply shown to each voter after they answer (Yes / No).
            "responses": [
                "We're all poor on the inside.",
                "What a glitch!",
            ],
        },
    },
    {
        # STEP 6 — collective doomscroll, but the bar is set by poll2: the reel
        # only advances once the share of the audience who swipe reaches the
        # share who voted "poor" (Yes = option 0) in poll2. Everyone can scroll;
        # it's the classic collective-threshold mechanic with a dynamic, vote-
        # derived threshold (see main.py collective_threshold).
        "id": "collective1",
        "label": "6 · Collective Doomscroll",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
        "threshold_from_poll": {"stage": "poll2", "option": 0},
        "scroll_feedback": {
            "waiting_text": "Got it — waiting on {n} more to scroll…",
            "vibrate_ms": 150,
        },
    },
    {
        # STEP 7 — another collective doomscroll, identical mechanic to stage 6
        # (same poll2-derived threshold + per-swiper feedback). Exists as its
        # own stage so TD gets a distinct stage_update / state number.
        "id": "collective2",
        "label": "7 · Collective Doomscroll 2",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
        "threshold_from_poll": {"stage": "poll2", "option": 0},
        "scroll_feedback": {
            "waiting_text": "Got it — waiting on {n} more to scroll…",
            "vibrate_ms": 150,
        },
    },
    {
        # STEP 8 (final) — slideshow of images with an overlay plea; one swipe by
        # a phone ends its show: black screen, "Thank you!", and a looping sound.
        # Terminal on the client (nothing else happens, the sound keeps playing).
        # Images (static/images/) and sound (static/sound/) are read live from
        # the folders, so the files can be swapped without editing this.
        "id": "finale",
        "label": "8 · Finale (slideshow → thank you)",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {
            "mode": "slideshow",
            "images": "auto",          # filled from static/images/ at send time
            "interval_ms": 300,        # 0.3s per image
            "overlay": "Finish this nightmare, wake me up pls",
        },
        "finale": {
            "text": "Thank you!",
            "sound": "auto",           # filled from static/sound/ at send time
            "loop": True,
        },
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
