const socket = io({
    transports: ['websocket', 'polling']
});

// DOM Elements
const screenText = document.getElementById('screen-text');
const screenImage = document.getElementById('screen-image');
const screenPoll = document.getElementById('screen-poll');
const mainText = document.getElementById('main-text');
const stageImage = document.getElementById('stage-image');
const pollQuestion = document.getElementById('poll-question');
const pollButtons = Array.from(document.querySelectorAll('.poll-opt'));

// State — everything is driven by the server's current stage.
let scrollEnabled = true;
let currentScreen = { mode: 'text', text: 'Scroll me' };
let pollActive = false;
let personalMessage = null;   // set after this phone votes; replaces the poll
let pulseOverride = null;     // admin's manual "next reel" pulse text
let pulseTimer = null;
let startY = 0;
let isSwiping = false;

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
    [screenText, screenImage, screenPoll].forEach(s => s.classList.add('hidden'));
    el.classList.remove('hidden');
}

// Render whatever the current stage (or active poll) demands.
function render() {
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
    if (pollActive) {
        show(screenPoll);
        document.body.classList.remove('black');
        return;
    }
    const s = currentScreen || {};
    if (s.mode === 'intro') {
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

// Socket Events
socket.on('connect', () => {
    console.log("Connected to server");
    // Announce ourselves; send any number we already hold so a reload keeps it.
    socket.emit('hello', { number: personNumber });
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
    const cfg = (data && data.config) || {};
    scrollEnabled = !!cfg.scroll_enabled;
    currentScreen = cfg.screen || { mode: 'text', text: 'Scroll me' };
    personalMessage = null;   // a new stage clears any leftover poll reply
    pulseOverride = null; clearTimeout(pulseTimer);   // and any leftover pulse
    console.log(`Stage: ${data.stage} (scroll ${scrollEnabled ? 'on' : 'off'})`);
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
    // Collective threshold reached — brief visual pulse as feedback.
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
    const endY = e.changedTouches[0].clientY;
    const diffY = startY - endY;

    // Detect upward swipe greater than 30 pixels
    if (diffY > 30 && scrollEnabled && !pollActive) {
        socket.emit('swipe', {});
        // Subtle bounce animation to show feedback that swipe worked
        mainText.classList.add('nudge');
        setTimeout(() => mainText.classList.remove('nudge'), 150);
    }
    isSwiping = false;
});
