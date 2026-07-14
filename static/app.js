const socket = io({
    transports: ['websocket', 'polling']
});

// DOM Elements
const screenText = document.getElementById('screen-text');
const screenImage = document.getElementById('screen-image');
const screenPoll = document.getElementById('screen-poll');
const screenSolo = document.getElementById('screen-solo');
const mainText = document.getElementById('main-text');
const stageImage = document.getElementById('stage-image');
const pollQuestion = document.getElementById('poll-question');
const pollButtons = Array.from(document.querySelectorAll('.poll-opt'));
const soloText = document.getElementById('solo-text');
const screenSlideshow = document.getElementById('screen-slideshow');
const slideImage = document.getElementById('slide-image');
const slideOverlay = document.getElementById('slide-overlay');

// State — everything is driven by the server's current stage.
let scrollEnabled = true;
let currentScreen = { mode: 'text', text: 'Scroll me' };
let pollActive = false;
let personalMessage = null;   // set after this phone votes; replaces the poll
let pulseOverride = null;     // admin's manual "next reel" pulse text
let pulseTimer = null;
let startY = 0;
let isSwiping = false;

// Collective-scroll per-swiper feedback (stages.py "scroll_feedback"): after you
// swipe, your phone buzzes and shows how many more scrolls are still needed,
// holding that until the reel actually advances.
let scrollFeedback = null;    // stage config object (or null when the stage lacks it)
let scrollWaiting = false;    // this phone has swiped and is waiting for the room
let scrollWaitText = '';

// Finale (stage 8): slideshow of images, then one swipe ends the show on this
// phone — black "Thank you!" + a looping sound. Terminal once entered.
let slideTimer = null;
let slideIndex = 0;
let finaleCfg = null;         // {text, sound, loop} for the current stage, if any
let finaleActive = false;     // this phone has ended the show (terminal)
let finaleAudio = null;

// One-at-a-time solo-scroll state (see stages.py "solo" field).
let soloActive = false;
let soloIsChosen = false;
let soloPhase = 'select';     // 'select' | 'result'
let soloTexts = {};

// Stable "you are the Nth person" label, assigned by the server on first open
// and cached so a reload keeps the same number for the whole performance.
let personNumber = parseInt(sessionStorage.getItem('scrollme_person'), 10) || null;

function ordinal(n) {
    const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function introText() {
    if (!personNumber) return 'Joining the dream…';
    return `You are the ${ordinal(personNumber)} person in my dream.\nLet's wait for the others to join.`;
}

function show(el) {
    [screenText, screenImage, screenPoll, screenSolo, screenSlideshow].forEach(s => s.classList.add('hidden'));
    el.classList.remove('hidden');
}

// Render whatever the current stage (or active poll / solo round) demands.
function render() {
    // Finale is terminal: once this phone has ended the show, nothing else can
    // take over the screen — black background, "Thank you!", sound keeps playing.
    if (finaleActive) {
        mainText.textContent = (finaleCfg && finaleCfg.text) || 'Thank you!';
        show(screenText);
        document.body.classList.add('black');
        return;
    }
    // The manual "next reel" pulse overrides everything else on screen until
    // its own timer clears it (see the manual_pulse handler below).
    if (pulseOverride) {
        mainText.textContent = pulseOverride;
        show(screenText);
        document.body.classList.remove('black');
        return;
    }
    // A personal poll reply takes over this phone's screen until the stage moves
    // on (or the poll ends), even though the poll is still live for everyone else.
    if (personalMessage) {
        mainText.textContent = personalMessage;
        show(screenText);
        document.body.classList.remove('black');
        return;
    }
    if (soloActive) {
        screenSolo.classList.toggle('chosen', soloIsChosen);
        soloText.textContent = soloIsChosen
            ? (soloPhase === 'result' ? (soloTexts.result || '') : (soloTexts.chosen || ''))
            : (soloTexts.not_chosen || '');
        show(screenSolo);
        document.body.classList.remove('black');
        return;
    }
    // Waiting-for-the-room feedback after this phone swiped in a collective stage.
    if (scrollWaiting) {
        mainText.textContent = scrollWaitText || 'Got it…';
        show(screenText);
        document.body.classList.remove('black');
        return;
    }
    if (pollActive) {
        show(screenPoll);
        document.body.classList.remove('black');
        return;
    }
    const s = currentScreen || {};
    if (s.mode === 'slideshow') {
        slideOverlay.textContent = s.overlay || '';
        show(screenSlideshow);
        document.body.classList.remove('black');
    } else if (s.mode === 'intro') {
        mainText.textContent = introText();
        show(screenText);
        document.body.classList.remove('black');
    } else if (s.mode === 'image' && s.image) {
        stageImage.src = s.image;
        show(screenImage);
        document.body.classList.remove('black');
    } else if (s.mode === 'black') {
        mainText.textContent = '';
        show(screenText);
        document.body.classList.add('black');
    } else if (s.mode === 'white') {
        mainText.textContent = '';
        show(screenText);
        document.body.classList.remove('black');
    } else {
        mainText.textContent = (s.text !== undefined && s.text !== null) ? s.text : 'Scroll me';
        show(screenText);
        document.body.classList.remove('black');
    }
}

function vibrate(pattern) {
    // Android Chrome only — iOS Safari has no Vibration API and ignores this.
    if (navigator.vibrate) navigator.vibrate(pattern || 200);
}

function stopSlideshow() {
    if (slideTimer) { clearInterval(slideTimer); slideTimer = null; }
}

function startSlideshow() {
    stopSlideshow();
    const imgs = (currentScreen && currentScreen.images) || [];
    if (!imgs.length) return;
    imgs.forEach(src => { const im = new Image(); im.src = src; });  // preload
    slideIndex = 0;
    slideImage.src = imgs[0];
    const interval = (currentScreen && currentScreen.interval_ms) || 300;
    slideTimer = setInterval(() => {
        slideIndex = (slideIndex + 1) % imgs.length;
        slideImage.src = imgs[slideIndex];
    }, interval);
}

// A swipe in the finale stage ends the show on THIS phone. Must run inside the
// swipe (a user gesture) so the browser lets the audio start.
function enterFinale() {
    if (finaleActive) return;
    finaleActive = true;
    stopSlideshow();
    socket.emit('finished', {});    // count me toward the live finale %
    render();                       // black screen + "Thank you!"
    const src = finaleCfg && finaleCfg.sound;
    if (src) {
        try {
            finaleAudio = new Audio(src);
            finaleAudio.loop = !finaleCfg || finaleCfg.loop !== false;
            finaleAudio.play().catch(() => {});
        } catch (e) { /* no audio available */ }
    }
}

// Socket Events
socket.on('connect', () => {
    console.log("Connected to server");
    // Announce ourselves; send any number we already hold so a reload keeps it.
    socket.emit('hello', { number: personNumber });
    // If we already ended the show, re-announce so we stay counted after a blip.
    if (finaleActive) socket.emit('finished', {});
});

socket.on('you_are', (data) => {
    personNumber = data.number;
    sessionStorage.setItem('scrollme_person', String(personNumber));
    console.log(`You are person #${personNumber}`);
    if (currentScreen && currentScreen.mode === 'intro') render();
});

socket.on('connect_error', (err) => {
    console.error("Connection Error:", err);
});

socket.on('disconnect', () => {
    console.log("Disconnected");
});

socket.on('stage_update', (data) => {
    if (finaleActive) return;   // the show has ended on this phone — ignore everything
    const cfg = (data && data.config) || {};
    scrollEnabled = !!cfg.scroll_enabled;
    currentScreen = cfg.screen || { mode: 'text', text: 'Scroll me' };
    personalMessage = null;   // a new stage clears any leftover poll reply
    pulseOverride = null; clearTimeout(pulseTimer);   // and any leftover pulse
    soloActive = false;       // and any leftover solo round (a fresh solo_update follows if the new stage has one)
    scrollFeedback = cfg.scroll_feedback || null;
    scrollWaiting = false; scrollWaitText = '';   // fresh round on the new stage
    finaleCfg = cfg.finale || null;
    if (currentScreen.mode === 'slideshow') startSlideshow(); else stopSlideshow();
    console.log(`Stage: ${data.stage} (scroll ${scrollEnabled ? 'on' : 'off'})`);
    render();
});

socket.on('scroll_wait', (data) => {
    // We swiped in a collective stage; show how many more are still needed.
    scrollWaiting = true;
    scrollWaitText = (data && data.text) || scrollWaitText;
    render();
});

socket.on('scroll_reset', () => {
    scrollWaiting = false; scrollWaitText = '';
    render();
});

socket.on('solo_update', (data) => {
    soloActive = !!(data && data.active);
    soloIsChosen = !!(data && data.chosen_sid && data.chosen_sid === socket.id);
    soloPhase = (data && data.phase) || 'select';
    soloTexts = (data && data.texts) || {};
    render();
});

socket.on('vibrate', (data) => {
    vibrate((data && data.pattern) || [300]);
});

socket.on('manual_pulse', (data) => {
    // Performer forced the next reel from admin — vibrate + show the pulse
    // line until the vibration ends, then fall back to the normal stage screen.
    const ms = (data && (data.ms || (data.pattern && data.pattern[0]))) || 600;
    pulseOverride = (data && data.text) || '';
    render();
    vibrate((data && data.pattern) || [ms]);
    clearTimeout(pulseTimer);
    pulseTimer = setTimeout(() => {
        pulseOverride = null;
        render();
    }, ms);
});

socket.on('poll_start', (data) => {
    pollActive = true;
    personalMessage = null;   // fresh poll — clear any previous reply
    pulseOverride = null; clearTimeout(pulseTimer);
    soloActive = false;
    pollQuestion.textContent = data.question || '';
    pollButtons.forEach((btn, i) => {
        btn.textContent = (data.options && data.options[i]) || '';
        btn.classList.remove('selected');
        btn.style.display = (data.options && data.options[i]) ? '' : 'none';
    });
    render();
});

socket.on('poll_end', () => {
    pollActive = false;
    personalMessage = null;
    render();
});

socket.on('vote_ack', (data) => {
    pollButtons.forEach((btn, i) => btn.classList.toggle('selected', i === data.option));
    // If this poll option carries a personal message, it takes over the screen.
    if (data.response) {
        personalMessage = data.response;
        render();
    }
});

socket.on('trigger_scroll', () => {
    // The reel advanced — clear any "waiting for the room" state and go back to
    // the normal stage screen ("Scroll me"), with a brief visual pulse.
    scrollWaiting = false; scrollWaitText = '';
    render();
    mainText.style.opacity = '0.15';
    setTimeout(() => { mainText.style.opacity = '1'; }, 400);
});

// Poll voting
pollButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
        socket.emit('vote', { option: parseInt(btn.dataset.i, 10) });
    });
});

// Touch Interaction (Swipe Up)
document.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
    isSwiping = true;
});

document.addEventListener('touchmove', (e) => {
    if (!isSwiping) return;
    e.preventDefault();
}, { passive: false });

document.addEventListener('touchend', (e) => {
    if (!isSwiping) return;
    isSwiping = false;
    if (finaleActive) return;   // show's over on this phone — swallow all input
    const endY = e.changedTouches[0].clientY;
    const diffY = startY - endY;

    // Finale stage: any upward swipe ends the show on this phone. Handled here
    // (not via the server) because starting the audio needs this user gesture.
    if (diffY > 30 && currentScreen && currentScreen.mode === 'slideshow') {
        enterFinale();
        return;
    }

    // In a solo round only the chosen phone (during 'select') may swipe;
    // otherwise fall back to the normal scroll_enabled + no-active-poll gate.
    // In a feedback stage, once you've swiped you're locked until the reel moves.
    const canSwipe = soloActive
        ? (soloIsChosen && soloPhase === 'select')
        : (scrollEnabled && !pollActive && !(scrollFeedback && scrollWaiting));

    // Detect upward swipe greater than 30 pixels
    if (diffY > 30 && canSwipe) {
        socket.emit('swipe', {});
        if (!soloActive && scrollFeedback) {
            // Buzz + flip to the "waiting on the room" screen; the server sends the
            // live remaining count via scroll_wait (shown text set there).
            vibrate([(scrollFeedback.vibrate_ms) || 150]);
            scrollWaiting = true;
            render();
        } else {
            // Subtle bounce animation to show feedback that swipe worked
            const el = soloActive ? soloText : mainText;
            el.classList.add('nudge');
            setTimeout(() => el.classList.remove('nudge'), 150);
        }
    }
});
