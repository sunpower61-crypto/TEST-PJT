const COLS = 10;
const ROWS = 20;
const BLOCK = 30;

const COLORS = {
  I: '#22d3ee',
  J: '#3b82f6',
  L: '#f97316',
  O: '#facc15',
  S: '#22c55e',
  T: '#a855f7',
  Z: '#ef4444',
};

const SHAPES = {
  I: [[1, 1, 1, 1]],
  J: [[1, 0, 0], [1, 1, 1]],
  L: [[0, 0, 1], [1, 1, 1]],
  O: [[1, 1], [1, 1]],
  S: [[0, 1, 1], [1, 1, 0]],
  T: [[0, 1, 0], [1, 1, 1]],
  Z: [[1, 1, 0], [0, 1, 1]],
};

const boardCanvas = document.getElementById('board');
const nextCanvas = document.getElementById('next');
const boardCtx = boardCanvas.getContext('2d');
const nextCtx = nextCanvas.getContext('2d');

const scoreEl = document.getElementById('score');
const levelEl = document.getElementById('level');
const linesEl = document.getElementById('lines');
const statusEl = document.getElementById('status');
const startBtn = document.getElementById('startBtn');
const pauseBtn = document.getElementById('pauseBtn');

const btnLeft = document.getElementById('btnLeft');
const btnRight = document.getElementById('btnRight');
const btnRotate = document.getElementById('btnRotate');
const btnSoft = document.getElementById('btnSoft');
const btnHard = document.getElementById('btnHard');

let board = createBoard();
let current = null;
let next = null;
let score = 0;
let level = 1;
let lines = 0;
let dropCounter = 0;
let lastTime = 0;
let running = false;
let paused = false;
let animationId = null;
let touchStart = null;

function createBoard() {
  return Array.from({ length: ROWS }, () => Array(COLS).fill(null));
}

function randomPiece() {
  const types = Object.keys(SHAPES);
  const type = types[Math.floor(Math.random() * types.length)];
  return {
    type,
    matrix: SHAPES[type].map((row) => [...row]),
    color: COLORS[type],
    x: Math.floor(COLS / 2) - 1,
    y: 0,
  };
}

function spawnPiece() {
  if (!next) next = randomPiece();
  current = next;
  current.x = Math.floor((COLS - current.matrix[0].length) / 2);
  current.y = 0;
  next = randomPiece();
  drawNext();

  if (collision(current.x, current.y, current.matrix)) gameOver();
}

function collision(offsetX, offsetY, matrix) {
  for (let y = 0; y < matrix.length; y++) {
    for (let x = 0; x < matrix[y].length; x++) {
      if (!matrix[y][x]) continue;
      const newX = x + offsetX;
      const newY = y + offsetY;
      if (newX < 0 || newX >= COLS || newY >= ROWS) return true;
      if (newY >= 0 && board[newY][newX]) return true;
    }
  }
  return false;
}

function merge() {
  current.matrix.forEach((row, y) => {
    row.forEach((value, x) => {
      if (value) board[current.y + y][current.x + x] = current.color;
    });
  });
}

function clearLines() {
  let cleared = 0;
  for (let y = ROWS - 1; y >= 0; y--) {
    if (board[y].every(Boolean)) {
      board.splice(y, 1);
      board.unshift(Array(COLS).fill(null));
      cleared += 1;
      y += 1;
    }
  }

  if (cleared > 0) {
    const points = [0, 100, 300, 500, 800][cleared];
    score += points * level;
    lines += cleared;
    level = 1 + Math.floor(lines / 10);
    updateHUD();
  }
}

function rotateMatrix(matrix) {
  const n = matrix.length;
  const m = matrix[0].length;
  const rotated = Array.from({ length: m }, () => Array(n).fill(0));
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < m; x++) {
      rotated[x][n - 1 - y] = matrix[y][x];
    }
  }
  return rotated;
}

function rotatePiece() {
  if (!current) return;
  const rotated = rotateMatrix(current.matrix);
  const kicks = [0, -1, 1, -2, 2];
  for (const kick of kicks) {
    if (!collision(current.x + kick, current.y, rotated)) {
      current.x += kick;
      current.matrix = rotated;
      return;
    }
  }
}

function move(dx) {
  if (!current) return;
  if (!collision(current.x + dx, current.y, current.matrix)) current.x += dx;
}

function drop() {
  if (!current) return false;
  if (!collision(current.x, current.y + 1, current.matrix)) {
    current.y += 1;
    return true;
  }

  merge();
  clearLines();
  spawnPiece();
  return false;
}

function hardDrop() {
  while (drop()) score += 2;
  updateHUD();
}

function softDrop() {
  if (drop()) {
    score += 1;
    updateHUD();
  }
}

function drawCell(ctx, x, y, color, size = BLOCK) {
  ctx.fillStyle = color;
  ctx.fillRect(x * size, y * size, size, size);
  ctx.strokeStyle = 'rgba(15, 23, 42, 0.45)';
  ctx.strokeRect(x * size, y * size, size, size);
}

function drawBoard() {
  boardCtx.clearRect(0, 0, boardCanvas.width, boardCanvas.height);
  board.forEach((row, y) => {
    row.forEach((cell, x) => {
      if (cell) drawCell(boardCtx, x, y, cell);
    });
  });

  if (current) {
    current.matrix.forEach((row, y) => {
      row.forEach((value, x) => {
        if (value) drawCell(boardCtx, current.x + x, current.y + y, current.color);
      });
    });
  }
}

function drawNext() {
  const previewBlock = 24;
  nextCtx.clearRect(0, 0, nextCanvas.width, nextCanvas.height);
  const shape = next.matrix;
  const offsetX = Math.floor((nextCanvas.width - shape[0].length * previewBlock) / 2 / previewBlock);
  const offsetY = Math.floor((nextCanvas.height - shape.length * previewBlock) / 2 / previewBlock);

  shape.forEach((row, y) => {
    row.forEach((value, x) => {
      if (value) drawCell(nextCtx, offsetX + x, offsetY + y, next.color, previewBlock);
    });
  });
}

function updateHUD() {
  scoreEl.textContent = score;
  levelEl.textContent = level;
  linesEl.textContent = lines;
}

function gameOver() {
  running = false;
  cancelAnimationFrame(animationId);
  statusEl.textContent = '게임 오버! 시작 / 재시작 버튼으로 다시 시작하세요.';
}

function togglePause() {
  if (!running) return;
  paused = !paused;
  statusEl.textContent = paused ? '일시정지됨' : '게임 진행 중';
  if (!paused) {
    lastTime = performance.now();
    animationId = requestAnimationFrame(update);
  }
}

function update(time = 0) {
  if (!running || paused) return;
  const delta = time - lastTime;
  lastTime = time;
  dropCounter += delta;

  const dropInterval = Math.max(1000 - (level - 1) * 80, 120);
  if (dropCounter >= dropInterval) {
    drop();
    dropCounter = 0;
  }

  drawBoard();
  animationId = requestAnimationFrame(update);
}

function resetGame() {
  board = createBoard();
  score = 0;
  level = 1;
  lines = 0;
  dropCounter = 0;
  running = true;
  paused = false;
  touchStart = null;
  next = randomPiece();
  spawnPiece();
  updateHUD();
  statusEl.textContent = '게임 진행 중';
  drawBoard();
  cancelAnimationFrame(animationId);
  lastTime = performance.now();
  animationId = requestAnimationFrame(update);
}

function executeAction(action) {
  if (!running || paused) return;

  if (action === 'left') move(-1);
  if (action === 'right') move(1);
  if (action === 'rotate') rotatePiece();
  if (action === 'soft') softDrop();
  if (action === 'hard') hardDrop();

  drawBoard();
}

function bindMobileButton(button, action) {
  const handler = (e) => {
    e.preventDefault();
    executeAction(action);
  };
  button.addEventListener('touchstart', handler, { passive: false });
  button.addEventListener('pointerdown', handler);
}

function handleBoardTouchStart(event) {
  const touch = event.touches[0];
  touchStart = { x: touch.clientX, y: touch.clientY, time: Date.now() };
}

function handleBoardTouchEnd(event) {
  if (!touchStart || !running || paused) return;

  const touch = event.changedTouches[0];
  const dx = touch.clientX - touchStart.x;
  const dy = touch.clientY - touchStart.y;
  const elapsed = Date.now() - touchStart.time;
  const absX = Math.abs(dx);
  const absY = Math.abs(dy);

  if (absX < 15 && absY < 15 && elapsed < 300) {
    rotatePiece();
  } else if (absY > 40 && dy > 0) {
    hardDrop();
  } else if (absX > 20) {
    move(dx > 0 ? 1 : -1);
  }

  drawBoard();
  touchStart = null;
}

document.addEventListener('keydown', (e) => {
  if (!running || paused) {
    if (e.key.toLowerCase() === 'p') togglePause();
    return;
  }

  if (e.key === 'ArrowLeft') move(-1);
  else if (e.key === 'ArrowRight') move(1);
  else if (e.key === 'ArrowUp') rotatePiece();
  else if (e.key === 'ArrowDown') softDrop();
  else if (e.code === 'Space') {
    e.preventDefault();
    hardDrop();
  } else if (e.key.toLowerCase() === 'p') {
    togglePause();
  }

  drawBoard();
});

startBtn.addEventListener('click', resetGame);
pauseBtn.addEventListener('click', togglePause);

bindMobileButton(btnLeft, 'left');
bindMobileButton(btnRight, 'right');
bindMobileButton(btnRotate, 'rotate');
bindMobileButton(btnSoft, 'soft');
bindMobileButton(btnHard, 'hard');

boardCanvas.addEventListener('touchstart', handleBoardTouchStart, { passive: true });
boardCanvas.addEventListener('touchend', handleBoardTouchEnd, { passive: true });

updateHUD();
drawBoard();
