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
                  entering the stage starts this poll. NOTE: no active stage
                  uses this anymore (the poll stages were archived — see
                  ARCHIVED_STAGES below); the engine is kept only for the
                  admin console's manual poll launcher.
  scroll_feedback optional {"waiting_text": "...{n}...", "vibrate_ms": N} on a
                  collective (non-solo) scroll stage. After a phone swipes it
                  buzzes and shows waiting_text (with {n} replaced by how many
                  MORE swipes the room still needs), refreshed live as others
                  swipe, until the reel advances — then it resets to the stage's
                  normal screen. Non-swipers are unaffected. See main.py
                  emit_scroll_feedback().
  threshold_from_poll
                  optional {"stage": "<poll stage id>", "option": <int>} — makes
                  a collective stage's swipe threshold DYNAMIC (the share of the
                  audience who picked that option in an earlier poll) instead of
                  the fixed config percentage. Currently UNUSED — the show now
                  runs on one steady rule: the reel advances when at least 50%
                  of the online audience swipe (config AUDIENCE_PERCENTAGE_
                  THRESHOLD). The capability is retained for future use; see
                  main.py collective_threshold().
  solo            optional one-at-a-time scroll mode (server picks one "chosen"
                  phone whose swipe alone advances the reel). Currently UNUSED —
                  the solo Scroll 1 stage was archived (see ARCHIVED_STAGES).
                  Kept working for future use; see main.py swipe().

--- Current show (active) ---------------------------------------------------
The live performance is now a tight five steps: gather → lost → two rounds of
collective doomscrolling → finale. The reel advances on ONE steady rule — at
least 50% of the currently-online audience must swipe (no poll-derived or
one-at-a-time thresholds). Poll 1 / Poll 2 / Scroll 1 (solo) and the old
placeholder stages were pulled out of the show and moved to ARCHIVED_STAGES
below — kept, not deleted, so they can be dropped back in (or replaced with new
stages the performer will script for those slots) without rewriting anything.
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
        # STEP 3 — collective doomscroll. One steady rule: everyone can scroll and
        # the reel advances the moment at least 50% of the currently-online
        # audience have swiped this round (fixed config bar, no poll derivation).
        "id": "collective1",
        "label": "3 · Collective Doomscroll",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
        "scroll_feedback": {
            "waiting_text": "Got it — waiting on {n} more to scroll…",
            "vibrate_ms": 150,
        },
    },
    {
        # STEP 4 — another collective doomscroll, identical 50% mechanic to stage
        # 3. Exists as its own stage so TD gets a distinct stage_update / state
        # number.
        "id": "collective2",
        "label": "4 · Collective Doomscroll 2",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
        "scroll_feedback": {
            "waiting_text": "Got it — waiting on {n} more to scroll…",
            "vibrate_ms": 150,
        },
    },
    {
        # STEP 5 (final) — slideshow of images with an overlay plea; one swipe by
        # a phone ends its show: black screen, "Thank you!", and a looping sound.
        # Terminal on the client (nothing else happens, the sound keeps playing).
        # Images (static/images/) and sound (static/sound/) are read live from
        # the folders, so the files can be swapped without editing this.
        "id": "finale",
        "label": "5 · Finale (slideshow → thank you)",
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
]

# --- Archived stages ---------------------------------------------------------
# Pulled out of the active show but intentionally KEPT (not deleted) so they can
# be re-inserted or replaced later. The server never loads this list — nothing
# here has a stage index and none appear in the admin rail. The performer plans
# to hand over new stages to occupy the poll1 / scroll1 / poll2 slots; until
# then their original definitions live here for reference / restore.
ARCHIVED_STAGES = [
    {
        # (was step 3) First audience poll — "feeling lost?" Yes/No with a
        # per-voter personal reply. Removed: the show no longer polls.
        "id": "poll1",
        "label": "Archived · Poll 1 — feeling lost?",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "white"},
        "poll": {
            "question": "Do you feel lost right now?",
            "options": ["Yes", "No"],
            "responses": [
                "you feel me",
                "Others in this room feel just like you.\nYou are not alone among the lost creatures here.",
            ],
        },
    },
    {
        # (was step 4) One-at-a-time solo scrolling. Removed: after "I Got Lost"
        # the show goes straight to collective doomscrolling.
        "id": "scroll1",
        "label": "Archived · Scroll 1 (one at a time)",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "white"},
        "solo": {
            "chosen_text": "You are the chosen one.\nScroll for us.",
            "result_text": "I know exactly what it feels like — this dopamine hit is mine.",
            "not_chosen_text": "You are not the selected one.",
            "result_hold_ms": 4000,
        },
    },
    {
        # (was step 5) Second audience poll — "are you poor?" It also used to
        # derive the collective threshold; that's gone (fixed 50% now).
        "id": "poll2",
        "label": "Archived · Poll 2 — are you poor?",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "white"},
        "poll": {
            "question": "Are you poor?",
            "options": ["Yes", "No"],
            "responses": [
                "We're all poor on the inside.",
                "What a glitch!",
            ],
        },
    },
    # Old pre-show / generic placeholder stages (never part of the scripted show).
    {
        "id": "idle",
        "label": "Archived · Idle / Pre-show",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "ScrollMe"},
    },
    {
        "id": "scroll",
        "label": "Archived · Scroll",
        "scroll_enabled": True,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Scroll me"},
    },
    {
        "id": "poll",
        "label": "Archived · Poll",
        "scroll_enabled": False,
        "vibrate_ms": 400,
        "screen": {"mode": "text", "text": ""},
        "poll": {"question": "Keep scrolling?", "options": ["Yes", "No"]},
    },
    {
        "id": "image",
        "label": "Archived · Image",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "image", "image": "static/images/1.jpg"},
    },
    {
        "id": "black",
        "label": "Archived · Blackout",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "black"},
    },
    {
        "id": "end",
        "label": "Archived · End",
        "scroll_enabled": False,
        "vibrate_ms": 0,
        "screen": {"mode": "text", "text": "Thank you"},
    },
]
