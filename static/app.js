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
let startY = 0;
let isSwiping = false;

function show(el) {
    [screenText, screenImage, screenPoll].forEach(s => s.classList.add('hidden'));
    el.classList.remove('hidden');
}

// Render whatever the current stage (or active poll) demands.
function render() {
    if (pollActive) {
        show(screenPoll);
        document.body.classList.remove('black');
        return;
    }
    const s = currentScreen || {};
    if (s.mode === 'image' && s.image) {
        stageImage.src = s.image;
        show(screenImage);
        document.body.classList.remove('black');
    } else if (s.mode === 'black') {
        mainText.textContent = '';
        show(screenText);
        document.body.classList.add('black');
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
    console.log(`Stage: ${data.stage} (scroll ${scrollEnabled ? 'on' : 'off'})`);
    render();
});

socket.on('vibrate', (data) => {
    vibrate((data && data.pattern) || [300]);
});

socket.on('poll_start', (data) => {
    pollActive = true;
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
    render();
});

socket.on('vote_ack', (data) => {
    pollButtons.forEach((btn, i) => btn.classList.toggle('selected', i === data.option));
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
