const configNode = document.getElementById("game-config");
const config = JSON.parse(configNode.textContent);

const MAX_ROWS = config.maxRows;
const WORD_LENGTH = config.wordLength;

const KEY_LAYOUTS = {
    normal: [
        ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
        ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
        ["ENTER", "Z", "X", "C", "V", "B", "N", "M", "BACKSPACE"],
        ["Ą", "Ć", "Ę", "Ł", "Ń", "Ó", "Ś", "Ź", "Ż"],
    ],
    easy: [
        ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
        ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
        ["ENTER", "Z", "X", "C", "V", "B", "N", "M", "BACKSPACE"],
    ],
};

const LETTER_SETS = {
    normal: new Set("AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŹŻ".split("")),
    easy: new Set("ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")),
};

const STATE_PRIORITY = { absent: 1, present: 2, correct: 3 };

const boardNode = document.getElementById("board");
const keyboardNode = document.getElementById("keyboard");
const statusNode = document.getElementById("status");
const modeInfoNode = document.getElementById("mode-info");

const settingsMenu = document.getElementById("settings-menu");
const menuNewGameButton = document.getElementById("menu-new-game");
const menuModeToggleButton = document.getElementById("menu-mode-toggle");
const aboutTriggerButton = document.getElementById("about-trigger");

const aboutModal = document.getElementById("about-modal");
const aboutCloseButton = document.getElementById("about-close");

let selectedMode = "normal";
let board = [];
let gameId = "";
let gameStatus = "in_progress";
let currentRow = 0;
let currentCol = 0;
let keyState = new Map();

// Show a status message and optionally style it as success or error.
function setStatus(message, type = "") {
    statusNode.textContent = message;
    statusNode.className = `status ${type}`.trim();
}

// Synchronize visible mode labels and menu button text with current game mode.
function syncModeUI() {
    const easyEnabled = selectedMode === "easy";

    if (menuModeToggleButton) {
        menuModeToggleButton.textContent = easyEnabled ? "WERSJA TRUDNA" : "WERSJA \u0141ATWA";
    }

    if (modeInfoNode) {
        modeInfoNode.textContent = easyEnabled
            ? "TRYB: WERSJA \u0141ATWA"
            : "TRYB: WERSJA TRUDNA";
    }
}

// Build an empty board grid and reset its DOM representation.
function initBoard() {
    board = Array.from({ length: MAX_ROWS }, () => Array(WORD_LENGTH).fill(""));
    boardNode.innerHTML = "";

    for (let row = 0; row < MAX_ROWS; row += 1) {
        for (let col = 0; col < WORD_LENGTH; col += 1) {
            const tile = document.createElement("div");
            tile.className = "tile";
            tile.dataset.row = String(row);
            tile.dataset.col = String(col);
            boardNode.appendChild(tile);
        }
    }
}

// Build the on-screen keyboard based on current mode layout.
function initKeyboard() {
    const layout = KEY_LAYOUTS[selectedMode] || KEY_LAYOUTS.normal;
    keyboardNode.innerHTML = "";

    for (const row of layout) {
        const rowNode = document.createElement("div");
        rowNode.className = "key-row";

        for (const keyLabel of row) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "key";
            button.dataset.key = keyLabel;
            button.textContent = keyLabel === "BACKSPACE" ? "⌫" : keyLabel;
            if (keyLabel === "ENTER" || keyLabel === "BACKSPACE") {
                button.classList.add("wide");
            }

            button.addEventListener("click", () => handleInput(keyLabel));
            rowNode.appendChild(button);
        }

        keyboardNode.appendChild(rowNode);
    }
}

// Return a board tile DOM node for the given row and column coordinates.
function getTile(row, col) {
    return boardNode.querySelector(`.tile[data-row="${row}"][data-col="${col}"]`);
}

// Update one board tile value and filled state.
function updateTile(row, col, value) {
    const tile = getTile(row, col);
    if (!tile) {
        return;
    }
    tile.textContent = value;
    tile.classList.toggle("filled", value !== "");
}

// Reset local gameplay state before starting a fresh game.
function resetLocalState() {
    currentRow = 0;
    currentCol = 0;
    gameStatus = "in_progress";
    keyState = new Map();
    setStatus("");
    initBoard();
    initKeyboard();
}

// Close the settings dropdown menu when it is currently open.
function closeSettingsMenu() {
    if (settingsMenu) {
        settingsMenu.removeAttribute("open");
    }
}

// Request a new game from backend and initialize local state from response.
async function startNewGame() {
    try {
        const response = await fetch("/api/new-game", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: selectedMode }),
        });

        const data = await response.json();
        if (!response.ok) {
            setStatus(data.message || "Nie udalo sie rozpoczac gry.", "error");
            return;
        }

        if (data.mode === "normal" || data.mode === "easy") {
            selectedMode = data.mode;
        }
        gameId = data.game_id;
        syncModeUI();
        resetLocalState();
    } catch {
        setStatus("Blad polaczenia z serwerem.", "error");
    }
}

// Open the about dialog and disable background page scrolling.
function openAboutModal() {
    if (!aboutModal) {
        return;
    }
    aboutModal.hidden = false;
    document.body.classList.add("modal-open");
}

// Close the about dialog and restore background page scrolling.
function closeAboutModal() {
    if (!aboutModal) {
        return;
    }
    aboutModal.hidden = true;
    document.body.classList.remove("modal-open");
}

// Map physical keyboard presses to in-game input actions.
function applyPhysicalKey(event) {
    if (event.key === "Escape" && aboutModal && !aboutModal.hidden) {
        event.preventDefault();
        closeAboutModal();
        return;
    }

    if (aboutModal && !aboutModal.hidden) {
        return;
    }

    if (event.ctrlKey || event.metaKey || event.altKey) {
        return;
    }

    const allowedKeys = LETTER_SETS[selectedMode] || LETTER_SETS.normal;

    if (event.key === "Enter") {
        event.preventDefault();
        handleInput("ENTER");
        return;
    }
    if (event.key === "Backspace") {
        event.preventDefault();
        handleInput("BACKSPACE");
        return;
    }

    const upper = event.key.toUpperCase();
    if (upper.length === 1 && allowedKeys.has(upper)) {
        event.preventDefault();
        handleInput(upper);
    }
}

// Insert one letter into the current row if there is free space.
function pushLetter(letter) {
    if (currentCol >= WORD_LENGTH) {
        return;
    }
    board[currentRow][currentCol] = letter;
    updateTile(currentRow, currentCol, letter);
    currentCol += 1;
}

// Remove the last typed letter from the current row.
function popLetter() {
    if (currentCol <= 0) {
        return;
    }
    currentCol -= 1;
    board[currentRow][currentCol] = "";
    updateTile(currentRow, currentCol, "");
}

// Animate a single tile and apply its final evaluation state.
function colorTile(tile, state, delay) {
    setTimeout(() => {
        tile.classList.add("flip");
        setTimeout(() => {
            tile.classList.remove("flip");
            tile.dataset.state = state;
        }, 110);
    }, delay);
}

// Apply evaluation colors to all tiles in a submitted row.
function colorRow(rowIndex, resultStates) {
    resultStates.forEach((state, colIndex) => {
        const tile = getTile(rowIndex, colIndex);
        if (tile) {
            colorTile(tile, state, colIndex * 180);
        }
    });
}

// Update keyboard key colors based on the best known letter states.
function updateKeyboard(guess, resultStates) {
    for (let index = 0; index < guess.length; index += 1) {
        const key = guess[index].toUpperCase();
        const newState = resultStates[index];
        const oldState = keyState.get(key);

        if (oldState && STATE_PRIORITY[oldState] >= STATE_PRIORITY[newState]) {
            continue;
        }
        keyState.set(key, newState);
        const keyNode = keyboardNode.querySelector(`.key[data-key="${key}"]`);
        if (keyNode) {
            keyNode.dataset.state = newState;
        }
    }
}

// Submit the current row as a guess and process API response.
async function submitGuess() {
    if (currentCol < WORD_LENGTH) {
        setStatus("Za krotkie slowo.", "error");
        return;
    }

    try {
        const guess = board[currentRow].join("").toLowerCase();
        const response = await fetch("/api/guess", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ game_id: gameId, guess }),
        });
        const data = await response.json();

        if (!response.ok) {
            setStatus(data.message || "Wystapil blad.", "error");
            return;
        }

        colorRow(currentRow, data.row_result);
        updateKeyboard(guess, data.row_result);

        if (data.game_status === "won") {
            gameStatus = "won";
            setStatus("Wygrana! Brawo!", "success");
            return;
        }
        if (data.game_status === "lost") {
            gameStatus = "lost";
            setStatus(data.message || "Przegrana.", "error");
            return;
        }

        currentRow += 1;
        currentCol = 0;
        setStatus("");
    } catch {
        setStatus("Blad polaczenia z serwerem.", "error");
    }
}

// Handle a single logical key press from physical or on-screen keyboard.
function handleInput(inputKey) {
    if (aboutModal && !aboutModal.hidden) {
        return;
    }

    if (gameStatus !== "in_progress") {
        if (inputKey === "ENTER") {
            startNewGame();
        }
        return;
    }

    const allowedKeys = LETTER_SETS[selectedMode] || LETTER_SETS.normal;

    if (inputKey === "ENTER") {
        submitGuess();
        return;
    }
    if (inputKey === "BACKSPACE") {
        popLetter();
        return;
    }
    if (inputKey.length === 1 && allowedKeys.has(inputKey)) {
        pushLetter(inputKey);
    }
}

window.addEventListener("keydown", applyPhysicalKey);

if (settingsMenu) {
    document.addEventListener("click", (event) => {
        if (!settingsMenu.contains(event.target)) {
            settingsMenu.removeAttribute("open");
        }
    });
}

if (menuNewGameButton) {
    menuNewGameButton.addEventListener("click", () => {
        startNewGame();
        closeSettingsMenu();
    });
}

if (menuModeToggleButton) {
    menuModeToggleButton.addEventListener("click", () => {
        selectedMode = selectedMode === "easy" ? "normal" : "easy";
        syncModeUI();
        startNewGame();
        closeSettingsMenu();
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

syncModeUI();
initBoard();
initKeyboard();
startNewGame();
