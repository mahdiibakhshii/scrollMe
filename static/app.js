const socket = io({
    transports: ['websocket', 'polling']
});

// DOM Elements
const statusImage = document.getElementById('status-image');

// State
let startY = 0;
let isSwiping = false;

// The images available in the folder.
// Ensure these map correctly to the assets you will eventually add in static/images/.
// Ordered from lowest to highest scroll threshold percentage.
const imagesList = [
    'static/images/1.jpg',
    'static/images/2.jpg',
    'static/images/3.jpg',
    'static/images/4.jpg',
    'static/images/5.jpg'
];

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

socket.on('stats_update', (data) => {
    // Normalize the progress relative to the trigger threshold.
    // If progress is at the threshold (e.g., 0.30) it becomes 1.0, meaning the final image is reached.
    const normalizedProgress = Math.min(data.progress / data.threshold, 1.0);
    
    // Convert normalized percentage to an image index
    const imageIndex = Math.min(
        Math.floor(normalizedProgress * imagesList.length), 
        imagesList.length - 1
    );
    
    const nextImage = imagesList[imageIndex];
    
    // Only update if it's changing
    if (!statusImage.src.includes(nextImage)) {
        statusImage.src = nextImage;
        console.log(`Progress: ${Math.round(data.progress*100)}% -> Showing image ${imageIndex + 1}/${imagesList.length}`);
    }
});

socket.on('trigger_scroll', (data) => {
    // Collect action reached threshold, visually react 
    // (e.g. blink the image out or jump straight back to 0)
    statusImage.style.opacity = '0'; // Flash to black (body background)
    
    setTimeout(() => {
        statusImage.src = imagesList[0];
        statusImage.style.opacity = '1';
    }, 500);
});

// Touch Interaction (Swipe Up is preserved!)
document.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
    isSwiping = true;
});

document.addEventListener('touchmove', (e) => {
    if (!isSwiping) return;
    e.preventDefault();
});

document.addEventListener('touchend', (e) => {
    if (!isSwiping) return;
    const endY = e.changedTouches[0].clientY;
    const diffY = startY - endY;

    // Detect upward wipe greater than 30 pixels
    if (diffY > 30) {
        socket.emit('swipe', {});
        // Subtle bounce animation to show feedback that swipe worked
        statusImage.style.transform = "translateY(-15px)";
        setTimeout(() => {
            statusImage.style.transform = "translateY(0)";
        }, 150);
    }
    isSwiping = false;
});
