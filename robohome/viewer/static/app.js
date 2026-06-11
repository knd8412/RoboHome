/* ═══════════════════════════════════════════════════
   ROBOHOME — app.js
   Handles: SocketIO events, canvas rendering, log UI
═══════════════════════════════════════════════════ */

// ── Canvas constants ───────────────────────────────
const GRID_W = 20;
const GRID_H = 15;

// World colours (matches CSS tokens)
const C = {
  bg:         '#080c18',
  floor:      '#1a2035',
  floorAlt:   '#161c2e',
  wall:       '#0a0e18',
  wallBorder: '#0f1520',
  doorClosed: '#7c3c0e',
  doorOpen:   '#d97706',
  roomLabel:  'rgba(100,116,139,0.5)',
  grid:       'rgba(30,45,71,0.7)',

  robot:      '#00d4ff',
  robotGlow:  'rgba(0,212,255,0.35)',
  robotFace:  '#ffffff',
  trail:      'rgba(0,212,255,0.18)',

  objDefault: '#334155',
  objText:    '#94a3b8',
};

// Object emoji map
const OBJ_EMOJI = {
  kettle:      '🫖', mug:        '☕', tea_bag:  '🍵',
  fridge:      '🧊', milk:       '🥛', sink:     '🚰',
  stove:       '🔥', counter:    '🔲', cupboard: '🗄️',
  trash_bin:   '🗑️', dirty_dish: '🍽️',
  sofa:        '🛋️', tv:         '📺', bookshelf:'📚',
  book:        '📖', coffee_table:'☕',
  bed:         '🛏️', desk:       '🖥️', lamp:     '💡',
  chair:       '🪑', keys:       '🗝️',
  toilet:      '🚽', basin:      '🪥', towel:    '🧺',
  coat_rack:   '🪝',
};

// Room label positions (rough center of each room in grid coords)
const ROOM_LABELS = {
  bedroom:     { x: 4.5,  y: 2.5, name: 'BEDROOM' },
  bathroom:    { x: 14.5, y: 2.5, name: 'BATHROOM' },
  hallway:     { x: 10,   y: 7,   name: 'HALLWAY' },
  kitchen:     { x: 4.5,  y: 12,  name: 'KITCHEN' },
  living_room: { x: 14.5, y: 12,  name: 'LIVING ROOM' },
};

// ── State ──────────────────────────────────────────
let socket = null;
let worldState = null;     // latest step data from server
let robotTrail = [];       // [{x, y}] fading trail
let autoScroll = true;
let paused = false;
let tileSize = 32;

// ── Canvas setup ───────────────────────────────────
const canvas = document.getElementById('world-canvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {
  const wrap = canvas.parentElement;
  const available_w = wrap.clientWidth  - 32;
  const available_h = wrap.clientHeight - 32;
  tileSize = Math.floor(Math.min(available_w / GRID_W, available_h / GRID_H));
  tileSize = Math.max(16, Math.min(tileSize, 40));
  canvas.width  = tileSize * GRID_W;
  canvas.height = tileSize * GRID_H;
  if (worldState) drawWorld(worldState);
  else drawBlankGrid();
}

window.addEventListener('resize', resizeCanvas);

// ── Draw: blank world grid ─────────────────────────
function drawBlankGrid() {
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Draw 5 rooms as faint regions
  const rooms = {
    bedroom:     { x:0,  y:0,  w:9,  h:5 },
    bathroom:    { x:10, y:0,  w:10, h:5 },
    hallway:     { x:0,  y:6,  w:20, h:3 },
    kitchen:     { x:0,  y:9,  w:9,  h:6 },
    living_room: { x:10, y:9,  w:10, h:6 },
  };

  for (const [name, r] of Object.entries(rooms)) {
    ctx.fillStyle = C.floor;
    ctx.fillRect(r.x * tileSize, r.y * tileSize, r.w * tileSize, r.h * tileSize);
  }

  // Draw walls between rooms
  drawStaticWalls();

  // Room labels
  ctx.font = `bold ${Math.max(7, tileSize * 0.28)}px 'JetBrains Mono', monospace`;
  ctx.fillStyle = C.roomLabel;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const [, info] of Object.entries(ROOM_LABELS)) {
    ctx.fillText(info.name, info.x * tileSize, info.y * tileSize);
  }
}

function drawStaticWalls() {
  ctx.fillStyle = C.wall;
  // Top of hallway: y=5 (row 5)
  for (let x = 0; x < GRID_W; x++) {
    ctx.fillRect(x * tileSize, 5 * tileSize, tileSize, tileSize);
  }
  // Bottom of hallway: y=8 — top of kitchen/living room: y=9
  for (let x = 0; x < GRID_W; x++) {
    ctx.fillRect(x * tileSize, 8 * tileSize, tileSize, tileSize);
  }
  // Vertical wall between bedroom/bathroom: x=9, y=0..4
  for (let y = 0; y < 5; y++) {
    ctx.fillRect(9 * tileSize, y * tileSize, tileSize, tileSize);
  }
  // Vertical wall between kitchen/living room: x=9, y=10..14
  for (let y = 10; y < GRID_H; y++) {
    ctx.fillRect(9 * tileSize, y * tileSize, tileSize, tileSize);
  }

  // Doors (closed, brown)
  ctx.fillStyle = C.doorClosed;
  // Bedroom door: (4, 5)
  ctx.fillRect(4 * tileSize, 5 * tileSize, tileSize, tileSize);
  // Bathroom door: (14, 5)
  ctx.fillRect(14 * tileSize, 5 * tileSize, tileSize, tileSize);
  // Kitchen door: (4, 8)
  ctx.fillRect(4 * tileSize, 8 * tileSize, tileSize, tileSize);
  // Living room door: (14, 8)
  ctx.fillRect(14 * tileSize, 8 * tileSize, tileSize, tileSize);

  drawGridLines();
}

function drawGridLines() {
  ctx.strokeStyle = C.grid;
  ctx.lineWidth = 0.5;
  for (let x = 0; x <= GRID_W; x++) {
    ctx.beginPath();
    ctx.moveTo(x * tileSize, 0);
    ctx.lineTo(x * tileSize, canvas.height);
    ctx.stroke();
  }
  for (let y = 0; y <= GRID_H; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * tileSize);
    ctx.lineTo(canvas.width, y * tileSize);
    ctx.stroke();
  }
}

// ── Draw: live world state from server ────────────
function drawWorld(data) {
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // 1. Draw grid cells
  const grid = data.grid || {};
  drawCells(grid);

  // 2. Draw room labels
  ctx.font = `bold ${Math.max(7, tileSize * 0.28)}px 'JetBrains Mono', monospace`;
  ctx.fillStyle = C.roomLabel;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const [, info] of Object.entries(ROOM_LABELS)) {
    ctx.fillText(info.name, info.x * tileSize, info.y * tileSize);
  }

  // 3. Draw robot trail
  for (let i = 0; i < robotTrail.length; i++) {
    const alpha = (i / robotTrail.length) * 0.4;
    ctx.fillStyle = `rgba(0,212,255,${alpha})`;
    const t = robotTrail[i];
    const cx = t.x * tileSize + tileSize / 2;
    const cy = t.y * tileSize + tileSize / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, tileSize * 0.12, 0, Math.PI * 2);
    ctx.fill();
  }

  // 4. Draw objects
  if (data.objects) {
    for (const obj of Object.values(data.objects)) {
      if (obj.position && typeof obj.position === 'object' && 'x' in obj.position) {
        drawObject(obj);
      }
    }
  }

  // 5. Draw robot
  if (data.robot) {
    drawRobot(data.robot);
  }
}

function drawCells(grid) {
  for (let y = 0; y < GRID_H; y++) {
    for (let x = 0; x < GRID_W; x++) {
      const cell = grid[`${x},${y}`];
      let color = C.floor;

      if (cell) {
        if (cell.cell_type === 'wall') color = C.wall;
        else if (cell.cell_type === 'door') {
          color = cell.is_open ? C.doorOpen : C.doorClosed;
        } else {
          // Checkerboard floor
          color = (x + y) % 2 === 0 ? C.floor : C.floorAlt;
        }
      } else {
        color = (x + y) % 2 === 0 ? C.floor : C.floorAlt;
      }

      ctx.fillStyle = color;
      ctx.fillRect(x * tileSize, y * tileSize, tileSize, tileSize);
    }
  }

  // Wall borders for a subtle 3D effect
  ctx.strokeStyle = C.wallBorder;
  ctx.lineWidth = 0.5;
  for (let y = 0; y < GRID_H; y++) {
    for (let x = 0; x < GRID_W; x++) {
      const cell = grid[`${x},${y}`];
      if (cell && cell.cell_type === 'wall') {
        ctx.strokeRect(x * tileSize + 0.5, y * tileSize + 0.5, tileSize - 1, tileSize - 1);
      }
    }
  }

  drawGridLines();
}

function drawObject(obj) {
  const px = obj.position.x * tileSize + tileSize / 2;
  const py = obj.position.y * tileSize + tileSize / 2;

  const emoji = OBJ_EMOJI[obj.type] || OBJ_EMOJI[obj.type.split('_')[0]] || '📦';
  const fontSize = Math.max(10, tileSize * 0.5);
  ctx.font = `${fontSize}px serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(emoji, px, py);
}

function drawRobot(robot) {
  const px = robot.position.x;
  const py = robot.position.y;
  const cx = px * tileSize + tileSize / 2;
  const cy = py * tileSize + tileSize / 2;
  const r  = tileSize * 0.36;

  // Outer glow
  const grd = ctx.createRadialGradient(cx, cy, r * 0.5, cx, cy, r * 2.2);
  grd.addColorStop(0, 'rgba(0,212,255,0.3)');
  grd.addColorStop(1, 'rgba(0,212,255,0)');
  ctx.fillStyle = grd;
  ctx.beginPath();
  ctx.arc(cx, cy, r * 2.2, 0, Math.PI * 2);
  ctx.fill();

  // Robot body
  ctx.fillStyle = '#00d4ff';
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();

  // Facing arrow
  ctx.strokeStyle = '#000';
  ctx.lineWidth = 2;
  ctx.lineCap = 'round';
  let ex = cx, ey = cy;
  const len = r * 0.8;
  if (robot.facing === 'north' || robot.facing === 'N') ey = cy - len;
  else if (robot.facing === 'south' || robot.facing === 'S') ey = cy + len;
  else if (robot.facing === 'east'  || robot.facing === 'E') ex = cx + len;
  else if (robot.facing === 'west'  || robot.facing === 'W') ex = cx - len;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(ex, ey);
  ctx.stroke();

  // Dot at head
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(ex, ey, 2.5, 0, Math.PI * 2);
  ctx.fill();
}

// ── SocketIO connection ────────────────────────────
function connectSocket() {
  if (socket) socket.disconnect();
  socket = io();

  socket.on('connect', () => {
    console.log('Connected to RoboHome server');
  });

  socket.on('step_event', (data) => {
    if (paused) return;
    handleStep(data);
  });

  socket.on('task_complete', (data) => {
    handleTaskComplete(data);
  });

  socket.on('disconnect', () => {
    setStatus('IDLE', '');
  });
}

// ── Step handler ───────────────────────────────────
function handleStep(data) {
  worldState = data;

  // Update robot trail
  if (data.robot) {
    const pos = data.robot.position;
    robotTrail.push({ x: pos.x, y: pos.y });
    if (robotTrail.length > 20) robotTrail.shift();
  }

  // Render canvas
  hideOverlay();
  drawWorld(data);

  // Update stats
  document.getElementById('stat-step').textContent = data.step ?? '—';
  document.getElementById('stat-room').textContent = data.robot?.room ?? '—';
  const holding = data.robot?.holding;
  document.getElementById('stat-holding').textContent =
    holding ? (holding.type || holding.id || 'item') : 'nothing';

  // Notes
  if (data.notes && data.notes.trim()) {
    const notesPanel = document.getElementById('notes-panel');
    notesPanel.style.display = 'block';
    document.getElementById('notes-body').textContent = data.notes.trim();
  }

  // Task bar
  if (data.task) {
    const tb = document.getElementById('task-bar');
    tb.style.display = 'flex';
    document.getElementById('task-text').textContent = data.task;
  }

  // Add step card to log
  addStepCard(data);
}

function handleTaskComplete(data) {
  const success = data.status === 'success';
  setStatus(success ? 'SUCCESS' : 'FAILED', success ? 'success' : 'failed');

  document.getElementById('btn-start').disabled = false;
  document.getElementById('btn-pause').disabled = true;

  // Done banner inside log
  const entries = document.getElementById('log-entries');
  const banner = document.createElement('div');
  banner.className = `done-banner ${success ? 'success' : 'failed'}`;
  banner.innerHTML = `
    <span class="done-icon">${success ? '✓' : '✕'}</span>
    <div>
      <div class="done-title">${success ? 'TASK COMPLETE' : 'TASK FAILED'}</div>
      <div class="done-detail">${data.steps ?? '?'} steps · ${data.message ?? ''}</div>
    </div>
  `;
  entries.appendChild(banner);
  if (autoScroll) entries.scrollTop = entries.scrollHeight;
}

// ── Log card builder ───────────────────────────────
function addStepCard(data) {
  const entries = document.getElementById('log-entries');

  // Remove empty placeholder
  const placeholder = entries.querySelector('.log-empty');
  if (placeholder) placeholder.remove();

  // Remove "latest" highlight from previous card
  const prev = entries.querySelector('.step-card.latest');
  if (prev) prev.classList.remove('latest');

  const last = data.last_action;
  const status = last?.result ?? 'success';
  const isFailed = status === 'failed' || status === 'error';
  const isNoted = last?.action === 'note';

  const card = document.createElement('div');
  card.className = `step-card latest ${isFailed ? 'failed' : isNoted ? 'noted' : 'success'}`;

  // Build args string
  let argsStr = '';
  if (last?.args) {
    const parts = Object.entries(last.args).map(([k, v]) => `${k}=<span>${v}</span>`);
    argsStr = `<div class="step-args mono">${parts.join('  ')}</div>`;
  }

  // Thought block
  const thought = data.thought || last?.thought;
  const thoughtHtml = thought
    ? `<div class="step-thought-toggle">
         <button class="thought-btn" onclick="toggleThought(this)">💭 THOUGHT</button>
         <div class="thought-body">${escHtml(thought)}</div>
       </div>`
    : '';

  const badgeClass = isFailed ? 'badge-failed' : isNoted ? 'badge-noted' : 'badge-success';
  const badgeText  = isFailed ? 'FAILED'       : isNoted ? 'NOTED'       : 'OK';

  card.innerHTML = `
    <div class="step-header">
      <span class="step-num mono">STEP ${data.step ?? '?'}</span>
      <span class="step-action mono">${last?.action ?? 'look_around'}</span>
      <span class="step-result-badge ${badgeClass}">${badgeText}</span>
    </div>
    ${last?.message ? `<div class="step-message">${escHtml(last.message)}</div>` : ''}
    ${argsStr}
    ${thoughtHtml}
  `;

  entries.appendChild(card);
  if (autoScroll) entries.scrollTop = entries.scrollHeight;
}

function toggleThought(btn) {
  const body = btn.nextElementSibling;
  body.classList.toggle('open');
  btn.textContent = body.classList.contains('open') ? '💭 HIDE' : '💭 THOUGHT';
}

// ── Controls ───────────────────────────────────────
function startRun() {
  const task = document.getElementById('task-select').value;
  resetLog();
  robotTrail = [];
  setStatus('RUNNING', 'running');
  document.getElementById('btn-start').disabled = true;
  document.getElementById('btn-pause').disabled = false;

  if (!socket) connectSocket();
  socket.emit('start_run', { task });
}

function togglePause() {
  paused = !paused;
  const btn = document.getElementById('btn-pause');
  btn.innerHTML = paused
    ? '<span class="btn-icon">▶</span> RESUME'
    : '<span class="btn-icon">⏸</span> PAUSE';
  setStatus(paused ? 'PAUSED' : 'RUNNING', paused ? '' : 'running');
}

function resetRun() {
  if (socket) socket.emit('reset');
  resetLog();
  robotTrail = [];
  worldState = null;
  paused = false;
  document.getElementById('btn-start').disabled = false;
  document.getElementById('btn-pause').disabled = true;
  document.getElementById('btn-pause').innerHTML = '<span class="btn-icon">⏸</span> PAUSE';
  document.getElementById('stat-step').textContent    = '—';
  document.getElementById('stat-room').textContent    = '—';
  document.getElementById('stat-holding').textContent = 'nothing';
  document.getElementById('notes-panel').style.display = 'none';
  document.getElementById('task-bar').style.display    = 'none';
  setStatus('IDLE', '');
  showOverlay();
  drawBlankGrid();
}

function resetLog() {
  const entries = document.getElementById('log-entries');
  entries.innerHTML = '<div class="log-empty"><span class="mono">Awaiting mission start...</span></div>';
}

function clearLog() {
  document.getElementById('log-entries').innerHTML = '';
}

function toggleAutoScroll() {
  autoScroll = !autoScroll;
  document.getElementById('btn-autoscroll').classList.toggle('active', autoScroll);
}

// ── Status helpers ─────────────────────────────────
function setStatus(text, state) {
  const badge = document.getElementById('status-badge');
  const label = document.getElementById('badge-text');
  badge.className = 'status-badge' + (state ? ` ${state}` : '');
  label.textContent = text;
}

function hideOverlay() {
  document.getElementById('canvas-overlay').classList.add('hidden');
}
function showOverlay() {
  document.getElementById('canvas-overlay').classList.remove('hidden');
}

// ── Util ───────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Boot ───────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  resizeCanvas();
  drawBlankGrid();
  connectSocket();
});