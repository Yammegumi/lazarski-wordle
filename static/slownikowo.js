const slownikowoConfigNode = document.getElementById("slownikowo-config");
const slownikowoConfig = JSON.parse(slownikowoConfigNode.textContent);
const MAX_ATTEMPTS = slownikowoConfig.maxAttempts;

const settingsMenu = document.getElementById("settings-menu");
const menuNewSlownikowoGameButton = document.getElementById("menu-new-slownikowo-game");
const aboutTriggerButton = document.getElementById("about-trigger");
const aboutModal = document.getElementById("about-modal");
const aboutCloseButton = document.getElementById("about-close");

const dotsNode = document.getElementById("slownikowo-dots");
const attemptsNode = document.getElementById("slownikowo-attempts");
const statusNode = document.getElementById("slownikowo-status");
const toastNode = document.getElementById("slownikowo-toast");
const formNode = document.getElementById("slownikowo-form");
const inputNode = document.getElementById("slownikowo-input");
const upListNode = document.getElementById("slownikowo-up-list");
const downListNode = document.getElementById("slownikowo-down-list");

let gameId = "";
let gameStatus = "in_progress";
let attempts = 0;
let upEntries = [];
let downEntries = [];
let toastTimer = null;

// Open the about modal and lock page scrolling while it is visible.
function openAboutModal() {
    if (!aboutModal) {
        return;
    }
    aboutModal.hidden = false;
    document.body.classList.add("modal-open");
}

// Close the about modal and restore page scrolling.
function closeAboutModal() {
    if (!aboutModal) {
        return;
    }
    aboutModal.hidden = true;
    document.body.classList.remove("modal-open");
}

// Render status text for final state messages (win/loss/errors).
function setStatus(message, type = "") {
    statusNode.textContent = message;
    statusNode.className = `status ${type}`.trim();
}

// Show a transient toast message for directional hints and non-final feedback.
function showToast(message, type = "") {
    if (!message) {
        return;
    }
    if (toastTimer !== null) {
        clearTimeout(toastTimer);
    }
    toastNode.textContent = message;
    toastNode.className = `slownikowo-toast show ${type}`.trim();
    toastNode.hidden = false;
    toastTimer = setTimeout(() => {
        toastNode.className = "slownikowo-toast";
        toastNode.hidden = true;
        toastTimer = null;
    }, 1800);
}

// Render current attempt usage out of the maximum available attempts.
function setAttempts() {
    attemptsNode.textContent = `Pr\u00f3by: ${attempts}/${MAX_ATTEMPTS}`;
}

// Close settings menu popover if currently open.
function closeSettingsMenu() {
    if (settingsMenu) {
        settingsMenu.removeAttribute("open");
    }
}

// Toggle input interactivity depending on whether the game is still active.
function setFormState(active) {
    inputNode.disabled = !active;
    if (active) {
        inputNode.placeholder = "WPISZ SLOWO";
    } else {
        inputNode.placeholder = "NOWA GRA";
    }
}

// Render attempt dots in left column and mark already used attempts.
function renderDots() {
    dotsNode.innerHTML = "";
    for (let index = 0; index < MAX_ATTEMPTS; index += 1) {
        const dot = document.createElement("li");
        dot.className = `slownikowo-dot ${index < attempts ? "used" : ""}`.trim();
        dotsNode.appendChild(dot);
    }
}

// Sort lane entries by dictionary position so visual order stays semantically correct.
function sortByDictionaryIndex(entries) {
    entries.sort((left, right) => {
        if (left.index !== right.index) {
            return left.index - right.index;
        }
        return left.word.localeCompare(right.word, "pl");
    });
}

// Interpolate one RGB component between two numeric values.
function lerp(start, end, factor) {
    return Math.round(start + (end - start) * factor);
}

// Build a color that gets greener when closer to target and grayer when farther.
function colorFromDistanceRatio(distanceRatio) {
    const ratio = Math.max(0, Math.min(1, distanceRatio));
    const green = [129, 220, 138];
    const yellow = [219, 205, 126];
    const gray = [224, 226, 231];

    let startColor = green;
    let endColor = yellow;
    let mix = ratio / 0.5;
    if (ratio > 0.5) {
        startColor = yellow;
        endColor = gray;
        mix = (ratio - 0.5) / 0.5;
    }
    mix = Math.max(0, Math.min(1, mix));

    const red = lerp(startColor[0], endColor[0], mix);
    const greenChannel = lerp(startColor[1], endColor[1], mix);
    const blue = lerp(startColor[2], endColor[2], mix);
    return `rgb(${red}, ${greenChannel}, ${blue})`;
}

// Render both upper and lower word lanes from sorted in-memory entries.
function renderLanes() {
    upListNode.innerHTML = "";
    for (const entry of upEntries) {
        const item = document.createElement("li");
        item.className = "slownikowo-lane-word up";
        item.textContent = entry.word.toUpperCase();
        item.style.color = colorFromDistanceRatio(entry.distanceRatio);
        upListNode.appendChild(item);
    }

    downListNode.innerHTML = "";
    for (const entry of downEntries) {
        const item = document.createElement("li");
        item.className = "slownikowo-lane-word down";
        item.textContent = entry.word.toUpperCase();
        item.style.color = colorFromDistanceRatio(entry.distanceRatio);
        downListNode.appendChild(item);
    }
}

// Reset local session state before requesting a new random target.
function resetUI() {
    gameStatus = "in_progress";
    attempts = 0;
    upEntries = [];
    downEntries = [];
    inputNode.value = "";
    setStatus("");
    setAttempts();
    renderDots();
    renderLanes();
    setFormState(true);
}

// Add one guess to the proper lane and keep lane order aligned with dictionary indices.
function addGuessToLane(guess, direction, guessIndex, distanceRatio) {
    if (direction === "correct") {
        return;
    }

    const entry = { word: guess, index: guessIndex, distanceRatio };
    if (direction === "up") {
        upEntries.push(entry);
        sortByDictionaryIndex(upEntries);
    } else if (direction === "down") {
        downEntries.push(entry);
        sortByDictionaryIndex(downEntries);
    }
    renderLanes();
}

// Request a new Slownikowo session where target word is randomized server-side.
async function startNewGame() {
    try {
        const response = await fetch("/api/slownikowo/new-game", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });
        const data = await response.json();

        if (!response.ok) {
            setStatus(data.message || "Nie udalo sie rozpoczac gry.", "error");
            return;
        }

        gameId = data.game_id;
        resetUI();
        closeSettingsMenu();
        inputNode.focus();
    } catch {
        setStatus("Blad polaczenia z serwerem.", "error");
    }
}

// Submit current input and render updated directional hints from server response.
async function submitGuess(event) {
    event.preventDefault();

    if (gameStatus !== "in_progress") {
        await startNewGame();
        return;
    }

    const guess = inputNode.value.trim().toLowerCase();
    if (!guess) {
        setStatus("Wpisz slowo.", "error");
        return;
    }

    try {
        const response = await fetch("/api/slownikowo/guess", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ game_id: gameId, guess }),
        });
        const data = await response.json();

        if (!response.ok) {
            setStatus(data.message || "Wystapil blad.", "error");
            if (response.status === 409 && data.game_status) {
                gameStatus = data.game_status;
                setFormState(false);
            }
            return;
        }

        attempts = data.attempt;
        setAttempts();
        renderDots();
        addGuessToLane(data.guess, data.direction, data.guess_index, data.distance_ratio);

        if (data.game_status === "won") {
            setStatus(`Brawo! Haslo: ${data.target_word.toUpperCase()}`, "success");
        } else if (data.game_status === "lost") {
            setStatus(`Koniec gry. Haslo: ${data.target_word.toUpperCase()}`, "error");
        } else {
            setStatus("");
            showToast(data.message || "", data.direction === "up" ? "up" : "down");
        }

        inputNode.value = "";
        gameStatus = data.game_status;
        if (gameStatus !== "in_progress") {
            setFormState(false);
        } else {
            inputNode.focus();
        }
    } catch {
        setStatus("Blad polaczenia z serwerem.", "error");
    }
}

if (settingsMenu) {
    document.addEventListener("click", (event) => {
        if (!settingsMenu.contains(event.target)) {
            closeSettingsMenu();
        }
    });
}

if (menuNewSlownikowoGameButton) {
    menuNewSlownikowoGameButton.addEventListener("click", () => {
        startNewGame();
    });
}

if (aboutTriggerButton) {
    aboutTriggerButton.addEventListener("click", () => {
        openAboutModal();
        closeSettingsMenu();
    });
}

if (aboutCloseButton) {
    aboutCloseButton.addEventListener("click", closeAboutModal);
}

if (aboutModal) {
    aboutModal.hidden = true;
    document.body.classList.remove("modal-open");

    aboutModal.addEventListener("click", (event) => {
        if (event.target === aboutModal) {
            closeAboutModal();
        }
    });
}

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && aboutModal && !aboutModal.hidden) {
        event.preventDefault();
        closeAboutModal();
    }
});

formNode.addEventListener("submit", submitGuess);
setAttempts();
renderDots();
renderLanes();
startNewGame();
