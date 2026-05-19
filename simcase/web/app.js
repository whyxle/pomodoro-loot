let state = null;
let autoOpenTimerId = null;
let autoOpenBusy = false;
let autoOpenStartInventoryByItem = {};
let focusTimerId = null;
let focusResetTimerId = null;
let focusCompleting = false;
let activeTabName = 'open';
let activeSettingsPane = 'general';
let collectionModeFilter = 'all';
const dropSoundPlayers = new Map();
const activeDropSounds = new Set();
const DROP_EVENT_TYPES = [
  ['normal', 'Обычная'],
  ['chest', 'Бонус'],
  ['boss', 'Большой итог'],
  ['legion', 'Много роллов'],
  ['abyss', 'Редкий прорыв'],
  ['mirror_altar', 'Дубликат'],
];
const DIFFICULTY_PROFILES = {
  1: { label: 'Разминка', bonusRolls: 0, luckRolls: 0, tone: 'Легкий вход' },
  2: { label: 'Обычная', bonusRolls: 0, luckRolls: 0, tone: 'Ровная работа' },
  3: { label: 'Сложная', bonusRolls: 1, luckRolls: 0, tone: 'Больше отдачи' },
  4: { label: 'Элитная', bonusRolls: 2, luckRolls: 1, tone: 'Высокая ставка' },
  5: { label: 'Босс', bonusRolls: 4, luckRolls: 2, tone: 'Максимальный контракт' },
};

function escapeHtml(value) {
  const raw = `${value ?? ''}`;
  return raw
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function imageSrc(path) {
  if (!path) return '';
  if (/^(https?:|data:|file:|\/)/i.test(path)) return path;
  return `file://${encodeURI(path.replaceAll('\\', '/'))}`;
}

function itemThumb(path, alt = '') {
  const src = imageSrc(path);
  if (!src) return '';
  return `<img class="item-thumb" src="${escapeHtml(src)}" alt="${escapeHtml(alt)}" loading="lazy" onerror="this.style.display='none'">`;
}

function setStatus(text, isError = false) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.classList.toggle('is-error', Boolean(text) && isError);
  el.classList.toggle('is-ok', Boolean(text) && !isError);
  el.style.color = isError ? 'var(--status-err)' : 'var(--status-ok)';
}

function tab(name) {
  activeTabName = name;
  const openLayout = document.getElementById('open-layout');
  if (openLayout) {
    openLayout.classList.toggle('hidden', name !== 'open');
  }
  for (const el of document.querySelectorAll('[id^="tab-"]')) {
    el.classList.add('hidden');
  }
  const chosen = document.getElementById(`tab-${name}`);
  if (chosen) {
    chosen.classList.remove('hidden');
  }
  for (const button of document.querySelectorAll('[data-tab-target]')) {
    const isActive = button.dataset.tabTarget === name;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  }
}

function rarityById(id) {
  return state.rarities.find((r) => r.id === id);
}

function badge(r) {
  if (!r) return '—';
  return `<span class="badge" style="color:${r.color};border-color:${r.color}">${r.name}</span>`;
}

function formatCollectionDate(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return '—';
  try {
    return new Date(value * 1000).toLocaleDateString('ru-RU');
  } catch (_err) {
    return '—';
  }
}

function raritySortValue(rarityId) {
  const rarity = rarityById(rarityId);
  const weight = Number((rarity && rarity.weight) || 0);
  return weight > 0 ? weight : Number.MAX_SAFE_INTEGER;
}

function previewItemForRarity(rarityId) {
  const candidates = state.items.filter((item) => item.rarity_id === rarityId);
  if (!candidates.length) return null;
  return [...candidates].sort((a, b) => {
    const weightDiff = (Number(b.weight) || 0) - (Number(a.weight) || 0);
    if (weightDiff !== 0) return weightDiff;
    return String(a.name || '').localeCompare(String(b.name || ''), 'ru');
  })[0];
}

function dropTitle(drop, titleOverride = null) {
  if (titleOverride !== null) return String(titleOverride);
  const itemName = (drop.item && drop.item.name) || '';
  const qty = Math.max(1, parseInt(drop.qty || 1, 10) || 1);
  if (qty <= 1) return itemName;
  const rarity = drop.rarity || {};
  const displayMax = Math.max(1, parseInt(rarity.stack_display_max || 99, 10));
  const qtyLabel = qty > displayMax ? `${displayMax}+x` : `${qty}x`;
  if (!itemName) return qtyLabel;
  return `${qtyLabel} ${itemName}`;
}

function dropCardMetrics(drop, titleOverride = null) {
  const rarity = drop.rarity || {};
  const title = dropTitle(drop, titleOverride);
  const estimatedTextWidth = title.length * Math.max(7, (Number(rarity.drop_font_size) || 18) * 0.62);
  const cardWidth = Math.max(140, Number(rarity.drop_box_width) || 220, Math.ceil(estimatedTextWidth + 24));
  const cardHeight = Math.max(36, Number(rarity.drop_box_height) || 56);
  return { title, cardWidth, cardHeight };
}

function dropCardMarkup(drop, options = {}) {
  const {
    titleOverride = null,
    wrapClass = 'drop-card-wrap',
    position = null,
  } = options;
  const safeDrop = {
    qty: Math.max(1, parseInt(drop.qty || 1, 10) || 1),
    item: drop.item || {},
    rarity: drop.rarity || {},
    drop_event: drop.drop_event || null,
  };
  const { title } = dropCardMetrics(safeDrop, titleOverride);
  const itemSrc = imageSrc(safeDrop.item.image_path);
  const img = itemSrc
    ? `<img class="drop-card-thumb" src="${escapeHtml(itemSrc)}" alt="${escapeHtml(safeDrop.item.name || '')}" loading="lazy" onerror="this.style.display='none'">`
    : '';
  const boxWidth = Math.max(120, Number(safeDrop.rarity.drop_box_width) || 260);
  const boxHeight = Math.max(36, Number(safeDrop.rarity.drop_box_height) || 60);
  const fontSize = Math.max(10, Number(safeDrop.rarity.drop_font_size) || 18);
  const dropVars = `--drop-color:${safeDrop.rarity.color || '#3b82f6'};--drop-bg:${safeDrop.rarity.drop_bg_color || '#0f172a'};--drop-text:${safeDrop.rarity.drop_text_color || '#e4ecfb'};--drop-border:${safeDrop.rarity.drop_border_color || safeDrop.rarity.color || '#3b82f6'};`;
  const positionVars = position ? `left:${position.x}px;top:${position.y}px;` : '';
  const wrapStyle = ` style="${positionVars}${dropVars}"`;
  const event = safeDrop.drop_event || {};
  const eventLabel = event.name && event.id !== 'normal'
    ? `<span class="drop-event-label">${escapeHtml(event.mirrored_duplicate ? 'Зеркальная копия' : event.name)}</span>`
    : '';
  return `<div class="${wrapClass}"${wrapStyle}>${eventLabel}<div>${img}</div><div class="drop-card" style="min-width:${boxWidth}px;min-height:${boxHeight}px;font-size:${fontSize}px;"><b>${escapeHtml(title)}</b></div></div>`;
}

function rarityPreviewMarkup(rarity, title = 'Preview') {
  const previewItem = previewItemForRarity(rarity.id);
  return dropCardMarkup(
    {
      qty: 1,
      item: previewItem || { name: title, image_path: '' },
      rarity,
    },
    {
      titleOverride: title,
      wrapClass: 'drop-preview-wrap',
    },
  );
}

function applyTheme(theme) {
  const safeTheme = theme === 'light' ? 'light' : 'dark';
  document.body.classList.toggle('theme-light', safeTheme === 'light');
}

function showSettingsPane(name) {
  const panes = ['general', 'focus', 'drop', 'drop-bg'];
  activeSettingsPane = panes.includes(name) ? name : 'general';
  for (const pane of panes) {
    const paneEl = document.getElementById(`settings-pane-${pane}`);
    const tabEl = document.getElementById(`settings-subtab-${pane}`);
    if (paneEl) paneEl.classList.toggle('hidden', activeSettingsPane !== pane);
    if (tabEl) tabEl.classList.toggle('primary', activeSettingsPane === pane);
  }
}

function updateDropBackgroundPreview() {
  const slider = document.getElementById('set-drop-bg-brightness');
  const valueEl = document.getElementById('set-drop-bg-brightness-value');
  if (!slider || !valueEl) return;
  valueEl.textContent = `${slider.value}%`;
}

function applyDropFloorVisuals(floorEl) {
  if (!floorEl) return;
  const dropVisuals = (state.settings && state.settings.drop_visuals) || {};
  const imagePath = dropVisuals.background_image_path || '';
  const brightnessRaw = Number(dropVisuals.background_brightness ?? 1);
  const brightness = Number.isFinite(brightnessRaw) ? Math.min(2, Math.max(0.2, brightnessRaw)) : 1;
  if (!imagePath) {
    floorEl.style.setProperty('--drop-floor-bg-image', 'none');
  } else {
    const src = imageSrc(imagePath);
    floorEl.style.setProperty('--drop-floor-bg-image', `url("${src}")`);
  }
  floorEl.style.setProperty('--drop-floor-bg-brightness', `${brightness}`);
}

function ensureDropSoundPlayer(path) {
  if (!path) return null;
  const soundPath = String(path).trim();
  if (!soundPath) return null;
  if (dropSoundPlayers.has(soundPath)) return dropSoundPlayers.get(soundPath);
  const audio = new Audio(imageSrc(soundPath));
  audio.preload = 'auto';
  dropSoundPlayers.set(soundPath, audio);
  return audio;
}

function playDropSound(path) {
  const baseAudio = ensureDropSoundPlayer(path);
  if (!baseAudio) return;
  const audio = baseAudio.cloneNode(true);
  audio.volume = baseAudio.volume;
  activeDropSounds.add(audio);
  const cleanup = () => activeDropSounds.delete(audio);
  audio.addEventListener('ended', cleanup, { once: true });
  audio.addEventListener('error', cleanup, { once: true });
  audio.play().catch(() => {
    cleanup();
  });
}

function renderPlayer() {
  const l = state.level;
  const focus = state.focus || {};
  const stats = state.stats || {};
  document.getElementById('player-level').textContent = `Lv.${l.level}`;
  document.getElementById('xp-bar').style.width = `${Math.round(l.progress * 100)}%`;
  document.getElementById('xp-meta').textContent = `${l.xp_in_level}/${l.xp_for_next} XP до следующего уровня`;
  document.getElementById('quick-stats').innerHTML = `
    <div class="stat-card"><small>Открыто кейсов</small><b>${state.stats.total_opened}</b></div>
    <div class="stat-card"><small>Потрачено</small><b>${state.stats.total_spent}</b></div>
  `;
  document.getElementById('xp-meta').textContent = `${l.xp_in_level}/${l.xp_for_next} XP до следующего уровня`;
  document.getElementById('quick-stats').innerHTML = `
    <div class="stat-card"><small>Минут фокуса</small><b>${Number(stats.total_focus_minutes || 0).toLocaleString('ru-RU')}</b></div>
    <div class="stat-card"><small>Сессий</small><b>${Number(stats.completed_focus_sessions || 0).toLocaleString('ru-RU')}</b></div>
    <div class="stat-card"><small>Цепочка</small><b>${Number(focus.focus_streak || 0)}</b></div>
    <div class="stat-card"><small>Лучшая</small><b>${Number(focus.best_focus_streak || 0)}</b></div>
  `;
}

function formatSeconds(totalSeconds) {
  const safe = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function formatChainWindow(totalSeconds) {
  const safe = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
  if (safe <= 0) return 'окно закрыто';
  const hours = Math.floor(safe / 3600);
  const minutes = Math.ceil((safe % 3600) / 60);
  if (hours <= 0) return `${minutes} мин`;
  return `${hours} ч ${String(minutes).padStart(2, '0')} мин`;
}

function difficultyProfile(level) {
  const safeLevel = Math.min(5, Math.max(1, parseInt(level || '2', 10) || 2));
  return { level: safeLevel, ...DIFFICULTY_PROFILES[safeLevel] };
}

function renderDifficultyContract() {
  const input = document.getElementById('focus-difficulty');
  const label = document.getElementById('difficulty-label');
  const preview = document.getElementById('difficulty-preview');
  if (!input || !label || !preview) return;
  const profile = difficultyProfile(input.value);
  input.value = profile.level;
  label.textContent = profile.label;
  const rewardParts = [];
  if (profile.bonusRolls > 0) rewardParts.push(`+${profile.bonusRolls} ролл.`);
  if (profile.luckRolls > 0) rewardParts.push(`удача +${profile.luckRolls}`);
  preview.textContent = rewardParts.length
    ? `${profile.tone}: ${rewardParts.join(' · ')}`
    : profile.tone;
  for (const button of document.querySelectorAll('[data-difficulty]')) {
    button.classList.toggle(
      'active',
      Number(button.dataset.difficulty) === profile.level,
    );
  }
}

function setDifficultyLevel(level) {
  const input = document.getElementById('focus-difficulty');
  if (!input || input.disabled) return;
  input.value = difficultyProfile(level).level;
  renderDifficultyContract();
}

function secondsUntilEpoch(epochSeconds) {
  const epoch = Number(epochSeconds || 0);
  if (!epoch) return 0;
  return Math.max(0, epoch - Date.now() / 1000);
}

function renderFocusResetTimers() {
  if (!state || !state.focus) return;
  const focus = state.focus || {};
  const chain = focus.chain || {};
  const dailyEl = document.getElementById('focus-daily-reset');
  const chainEl = document.getElementById('focus-chain-reset');
  if (dailyEl) {
    dailyEl.textContent = focus.daily_reset_at
      ? formatChainWindow(secondsUntilEpoch(focus.daily_reset_at))
      : '—';
  }
  if (chainEl) {
    const currentChain = Number(chain.current ?? focus.focus_streak ?? 0);
    if (!currentChain) {
      chainEl.textContent = 'нет цепочки';
    } else if (focus.active_session && chain.continues) {
      chainEl.textContent = 'удержана';
    } else if (chain.deadline_at) {
      chainEl.textContent = formatChainWindow(secondsUntilEpoch(chain.deadline_at));
    } else {
      chainEl.textContent = '—';
    }
  }
}

function renderActivityCalendar() {
  const calendar = document.getElementById('activity-calendar');
  const total = document.getElementById('activity-total');
  if (!calendar || !state || !state.focus) return;
  const days = state.focus.activity_calendar || [];
  const recentMinutes = days.reduce((sum, day) => sum + Number(day.minutes || 0), 0);
  if (total) total.textContent = `${recentMinutes.toLocaleString('ru-RU')}м`;
  calendar.innerHTML = days.map((day) => {
    const minutes = Number(day.minutes || 0);
    const sessions = Number(day.sessions || 0);
    const title = `${day.date}: ${minutes}м, ${sessions} сесс.`;
    return `<span class="activity-day" data-level="${Number(day.intensity || 0)}" title="${escapeHtml(title)}"></span>`;
  }).join('');
}

function activeFocusSession() {
  return state && state.focus ? state.focus.active_session || null : null;
}

function stopFocusTimer() {
  if (focusTimerId !== null) {
    clearInterval(focusTimerId);
    focusTimerId = null;
  }
}

function updateFocusTimer() {
  const session = activeFocusSession();
  const timeEl = document.getElementById('focus-time');
  const statusEl = document.getElementById('focus-status');
  const fillEl = document.getElementById('focus-ring-fill');
  const completeButton = document.getElementById('focus-complete');
  if (!timeEl || !statusEl || !fillEl || !completeButton) return;

  if (!session) {
    const duration = parseInt(document.getElementById('focus-duration')?.value || '25', 10) || 25;
    timeEl.textContent = formatSeconds(duration * 60);
    statusEl.textContent = 'Сессия не активна';
    fillEl.style.width = '0%';
    completeButton.disabled = true;
    return;
  }

  const now = Date.now() / 1000;
  const startedAt = Number(session.started_at || now);
  const endsAt = Number(session.ends_at || now);
  const total = Math.max(1, endsAt - startedAt);
  const remaining = Math.max(0, endsAt - now);
  const progress = Math.min(1, Math.max(0, 1 - remaining / total));
  timeEl.textContent = formatSeconds(remaining);
  statusEl.textContent = remaining > 0
    ? `В работе: ${session.task_title || 'Фокус-сессия'}`
    : 'Сессия завершена, раскрываем награду';
  fillEl.style.width = `${Math.round(progress * 100)}%`;
  completeButton.disabled = remaining > 0 || focusCompleting;

  if (remaining <= 0 && !focusCompleting) {
    completeFocusSession();
  }
  renderFocusResetTimers();
}

function renderFocus() {
  const focus = state.focus || {};
  const session = focus.active_session || null;
  const startButton = document.getElementById('focus-start');
  const cancelButton = document.getElementById('focus-cancel');
  const taskInput = document.getElementById('focus-task');
  const durationInput = document.getElementById('focus-duration');
  const difficultyInput = document.getElementById('focus-difficulty');
  const todayTotal = document.getElementById('focus-today-total');
  const questsEl = document.getElementById('focus-quests');
  const historyEl = document.getElementById('focus-history');
  const summaryEl = document.getElementById('open-summary');
  const chain = focus.chain || {};
  const chainCountEl = document.getElementById('focus-chain-count');
  const chainMetaEl = document.getElementById('focus-chain-meta');
  const chainNextEl = document.getElementById('focus-chain-next');

  if (!startButton || !cancelButton || !taskInput || !durationInput) return;

  const running = Boolean(session);
  startButton.disabled = running;
  cancelButton.disabled = !running;
  taskInput.disabled = running;
  durationInput.disabled = running;
  if (difficultyInput) difficultyInput.disabled = running;
  if (session) {
    taskInput.value = session.task_title || '';
    durationInput.value = session.duration_minutes || 25;
    if (difficultyInput) difficultyInput.value = session.difficulty_level || 2;
    if (summaryEl) summaryEl.textContent = `Цепочка: ${Number(focus.focus_streak || 0)}`;
    if (focusTimerId === null) {
      focusTimerId = setInterval(updateFocusTimer, 500);
    }
  } else {
    stopFocusTimer();
    if (summaryEl) summaryEl.textContent = 'Готово к фокусу';
  }

  if (todayTotal) {
    todayTotal.textContent = `${Number(focus.today_minutes || 0)}м`;
  }
  if (chainCountEl && chainMetaEl && chainNextEl) {
    const currentChain = Number(chain.current ?? focus.focus_streak ?? 0);
    const nextCount = Number(chain.next_count || 1);
    const bonusRolls = Number(chain.next_bonus_rolls || 0);
    const luckRolls = Number(chain.next_luck_rolls || 1);
    const dailyCap = Number(chain.daily_bonus_roll_cap || 0);
    const dailyLeft = Number(chain.daily_bonus_rolls_left || 0);
    const capLabel = dailyCap > 0 ? ` · лимит ${dailyLeft}/${dailyCap}` : '';
    chainCountEl.textContent = `x${currentChain}`;
    chainNextEl.textContent = `#${nextCount}: +${bonusRolls} ролл. · удача x${luckRolls}${capLabel}`;
    if (session && chain.continues) {
      chainMetaEl.textContent = 'Эта сессия уже удерживает цепочку. Награда усилится после завершения.';
    } else if (currentChain > 0 && Number(chain.seconds_left || 0) > 0) {
      chainMetaEl.textContent = `Начните следующую сессию за ${formatChainWindow(chain.seconds_left)}. Окно: ${Number(chain.break_window_minutes || 150)} мин.`;
    } else if (currentChain > 0) {
      chainMetaEl.textContent = 'Окно цепочки закрыто. Следующая сессия начнет новый разгон.';
    } else {
      chainMetaEl.textContent = `Завершите сессию, затем возвращайтесь в течение ${Number(chain.break_window_minutes || 150)} мин.`;
    }
  }
  if (questsEl) {
    const quests = focus.daily_quests || [];
    questsEl.innerHTML = quests.map((quest) => {
      const done = quest.completed || quest.claimed;
      const value = Number(quest.value || 0);
      const target = Number(quest.target || 0);
      return `
        <div class="quest-row ${done ? 'is-done' : ''}">
          <span>${escapeHtml(quest.label || quest.id)}</span>
          <b>${Math.min(value, target)}/${target}</b>
        </div>
      `;
    }).join('') || '<small>Цели дня появятся после первой сессии</small>';
  }
  if (historyEl) {
    const sessions = (focus.completed_sessions || []).slice(0, 5);
    historyEl.innerHTML = sessions.map((row) => `
      <div class="history-row">
        <span>${escapeHtml(row.task_title || 'Фокус-сессия')}</span>
        <b>${Number(row.duration_minutes || 0)}м · ${escapeHtml(difficultyProfile(row.difficulty_level || 2).label)}${row.chain_count ? ` · x${Number(row.chain_count)}` : ''}</b>
      </div>
    `).join('') || '<small>Здесь появятся завершенные сессии</small>';
  }

  renderDifficultyContract();
  renderFocusResetTimers();
  renderActivityCalendar();
  updateFocusTimer();
}

function itemRaritySelect(value) {
  return `<select data-k="rarity_id">${state.rarities.map((r) => `<option value="${r.id}" ${r.id === value ? 'selected' : ''}>${r.name}</option>`).join('')}</select>`;
}

function renderItems() {
  document.getElementById('item-rarity').innerHTML = state.rarities.map((r) => `<option value="${r.id}">${r.name}</option>`).join('');
  const rarityOrder = new Map(
    [...state.rarities]
      .sort((a, b) => {
        const weightDiff = (Number(b.weight) || 0) - (Number(a.weight) || 0);
        if (weightDiff !== 0) return weightDiff;
        return String(a.name || '').localeCompare(String(b.name || ''), 'ru');
      })
      .map((rarity, idx) => [rarity.id, idx]),
  );
  const rows = [...state.items]
    .sort((a, b) => {
      const rarityDiff = (rarityOrder.get(a.rarity_id) ?? Number.MAX_SAFE_INTEGER) - (rarityOrder.get(b.rarity_id) ?? Number.MAX_SAFE_INTEGER);
      if (rarityDiff !== 0) return rarityDiff;
      const weightDiff = (Number(b.weight) || 0) - (Number(a.weight) || 0);
      if (weightDiff !== 0) return weightDiff;
      return String(a.name || '').localeCompare(String(b.name || ''), 'ru');
    })
    .map((i) => `<tr data-id="${i.id}"><td><input data-k="name" value="${escapeHtml(i.name)}"></td><td>${itemRaritySelect(i.rarity_id)}</td><td><input data-k="weight" type="number" step="0.1" min="0" value="${i.weight}" style="width:90px"></td><td><div class="row">${itemThumb(i.image_path, i.name)}<input data-k="image_path" value="${escapeHtml(i.image_path || '')}" placeholder="URL картинки"></div></td><td><input data-k="description" value="${escapeHtml(i.description || '')}" placeholder="Описание"></td><td><label><input type="checkbox" data-k="is_currency" ${i.is_currency ? 'checked' : ''}> Валюта</label></td><td><button onclick="delItem('${i.id}')">Удалить</button></td></tr>`)
    .join('');
  document.getElementById('items-table').innerHTML = `<tr><th>Название</th><th>Редкость</th><th>Вес</th><th>Картинка + превью</th><th>Описание</th><th>Теги</th><th></th></tr>${rows}`;
}

function renderRarities() {
  const rows = [...state.rarities]
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .map((r) => `<tr data-id="${r.id}"><td><input data-k="name" value="${r.name}"></td><td><input data-k="weight" type="number" min="0" step="0.1" value="${r.weight || 0}" style="width:90px"></td><td><small>${(state.rarity_probabilities && state.rarity_probabilities[r.id] || 0).toFixed(3)}%</small></td><td><input data-k="color" type="color" value="${r.color}"></td><td><input data-k="drop_bg_color" type="color" value="${r.drop_bg_color || '#0f172a'}"></td><td><input data-k="drop_text_color" type="color" value="${r.drop_text_color || '#e4ecfb'}"></td><td><input data-k="drop_border_color" type="color" value="${r.drop_border_color || r.color}"></td><td><input data-k="drop_box_width" type="number" min="120" value="${r.drop_box_width || 260}" style="width:82px"></td><td><input data-k="drop_box_height" type="number" min="36" value="${r.drop_box_height || 60}" style="width:82px"></td><td><input data-k="drop_font_size" type="number" min="10" value="${r.drop_font_size || 18}" style="width:82px"></td><td><input data-k="stack_max_size" type="number" min="1" value="${r.stack_max_size || 10}" style="width:82px"></td><td><input data-k="stack_display_max" type="number" min="1" value="${r.stack_display_max || 99}" style="width:82px"></td><td><div class="row"><input data-k="drop_sound" value="${r.drop_sound || ''}" style="min-width:180px"><button onclick="pickSoundForRow('${r.id}')">…</button></div></td><td>${rarityPreviewMarkup(r)}</td><td><button onclick="delRarity('${r.id}')">Удалить</button></td></tr>`)
    .join('');
  document.getElementById('rarities-table').innerHTML = `<tr><th>Название</th><th>Вес</th><th>Шанс</th><th>Цвет</th><th>Фон</th><th>Текст</th><th>Контур</th><th>Ширина</th><th>Высота</th><th>Текст(px)</th><th>Стопка макс.</th><th>Показ макс.</th><th>Звук</th><th>Превью</th><th></th></tr>${rows}`;
}

function rarityOptions(selectedId = '') {
  return state.rarities
    .map((r) => `<option value="${r.id}" ${r.id === selectedId ? 'selected' : ''}>${escapeHtml(r.name)}</option>`)
    .join('');
}

function renderRarityGradations() {
  const sortedRarities = [...state.rarities].sort((a, b) => (b.weight || 0) - (a.weight || 0));
  const html = sortedRarities.map((rarity) => {
    const rules = [...(rarity.stack_rarity_upgrades || [])].sort((a, b) => (a.min_qty || 0) - (b.min_qty || 0));
    const rulesRows = rules.length
      ? rules.map((rule, idx) => `
        <tr>
          <td style="width:200px"><input type="number" min="1" value="${Math.max(1, parseInt(rule.min_qty || 1, 10))}" onchange="updateRarityUpgradeMinQty('${rarity.id}', ${idx}, this.value)"></td>
          <td><select onchange="updateRarityUpgradeTarget('${rarity.id}', ${idx}, this.value)">${rarityOptions(rule.target_rarity_id)}</select></td>
          <td style="width:130px"><button class="danger" onclick="removeRarityUpgradeCondition('${rarity.id}', ${idx})">Удалить</button></td>
        </tr>
      `).join('')
      : '<tr><td colspan="3"><i>Условия не добавлены</i></td></tr>';
    return `
      <div class="card" style="margin-bottom:10px">
        <div class="row" style="justify-content:space-between">
          <div class="row"><b>${escapeHtml(rarity.name)}</b> ${rarityPreviewMarkup(rarity)}</div>
          <button onclick="addRarityUpgradeCondition('${rarity.id}')">Добавить условие</button>
        </div>
        <table style="margin-top:8px">
          <tr><th>От количества в стопке</th><th>Показывать как редкость</th><th></th></tr>
          ${rulesRows}
        </table>
      </div>
    `;
  }).join('');
  document.getElementById('rarity-gradations-table').innerHTML = html || '<i>Нет редкостей</i>';
}

function intersects(a, b) {
  return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
}

function createDropLayout(drops, floorWidth) {
  const placements = [];
  const gap = 12;
  const imageSlotWidth = 42;
  let floorHeight = 340;
  for (const drop of drops) {
    const { cardWidth, cardHeight } = dropCardMetrics(drop);
    const w = cardWidth + imageSlotWidth + gap + 18;
    const h = cardHeight + 12;
    let placed = null;
    for (let attempt = 0; attempt < 220; attempt += 1) {
      const maxX = Math.max(0, floorWidth - w);
      const maxY = Math.max(0, floorHeight - h);
      const candidate = {
        x: Math.floor(Math.random() * (maxX + 1)),
        y: Math.floor(Math.random() * (maxY + 1)),
        w,
        h,
      };
      if (!placements.some((p) => intersects(candidate, p))) {
        placed = candidate;
        break;
      }
    }
    if (!placed) {
      floorHeight += h + gap;
      const maxX = Math.max(0, floorWidth - w);
      placed = { x: Math.floor(Math.random() * (maxX + 1)), y: floorHeight - h - gap, w, h };
    }
    placements.push(placed);
    floorHeight = Math.max(floorHeight, placed.y + h + gap);
  }
  return { placements, floorHeight };
}

function renderInventory() {
  const rows = Object.entries(state.inventory)
    .map(([id, c]) => {
      const i = state.items.find((x) => x.id === id);
      if (!i) return '';
      return `<tr><td><span class="item-cell">${itemThumb(i.image_path, i.name)}${i.name}</span></td><td>${c}</td><td><div class="row"><input id="consume-${id}" type="number" min="1" value="1" style="width:90px"><button onclick="consumeItem('${id}')">Списать</button></div></td></tr>`;
    })
    .join('');
  document.getElementById('inventory-table').innerHTML = `<tr><th>Предмет</th><th>Кол-во</th><th>Списание</th></tr>${rows || '<tr><td colspan="3"><i>Инвентарь пуст</i></td></tr>'}`;
}

function collectionRecord(itemId) {
  const collection = state.collection || {};
  const items = collection.items || {};
  const record = items[itemId] || null;
  return record && Number(record.found_count || 0) > 0 ? record : null;
}

function renderCollection() {
  const grid = document.getElementById('collection-grid');
  const summaryEl = document.getElementById('collection-summary');
  const raritySelect = document.getElementById('collection-rarity-filter');
  const searchInput = document.getElementById('collection-search');
  if (!grid || !summaryEl || !raritySelect || !searchInput) return;

  const previousRarity = raritySelect.value || 'all';
  raritySelect.innerHTML = `<option value="all">Все редкости</option>${state.rarities.map((r) => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('')}`;
  raritySelect.value = state.rarities.some((r) => r.id === previousRarity) ? previousRarity : 'all';

  for (const button of document.querySelectorAll('[data-collection-mode]')) {
    button.classList.toggle('active', button.dataset.collectionMode === collectionModeFilter);
  }

  const summary = state.collection_summary || {};
  const rarest = summary.rarest_item || null;
  const rarestLabel = rarest && rarest.item
    ? `${escapeHtml(rarest.item.name || '')}${rarest.rarity ? ` · ${escapeHtml(rarest.rarity.name || '')}` : ''}`
    : '—';
  summaryEl.innerHTML = `
    <div class="stat-card"><small>Заполнено</small><b>${Number(summary.completion_percent || 0).toFixed(2)}%</b></div>
    <div class="stat-card"><small>Найдено</small><b>${Number(summary.found_items || 0)}/${Number(summary.total_items || 0)}</b></div>
    <div class="stat-card"><small>Всего копий</small><b>${Number(summary.total_found_copies || 0).toLocaleString('ru-RU')}</b></div>
    <div class="stat-card"><small>Самая редкая находка</small><b>${rarestLabel}</b></div>
  `;

  const selectedRarity = raritySelect.value;
  const query = searchInput.value.trim().toLocaleLowerCase('ru-RU');
  const filtered = [...state.items]
    .filter((item) => {
      const record = collectionRecord(item.id);
      if (collectionModeFilter === 'found' && !record) return false;
      if (collectionModeFilter === 'missing' && record) return false;
      if (selectedRarity !== 'all' && item.rarity_id !== selectedRarity) return false;
      if (query && !String(item.name || '').toLocaleLowerCase('ru-RU').includes(query)) return false;
      return true;
    })
    .sort((a, b) => {
      const rarityDiff = raritySortValue(a.rarity_id) - raritySortValue(b.rarity_id);
      if (rarityDiff !== 0) return rarityDiff;
      const foundDiff = Number(Boolean(collectionRecord(b.id))) - Number(Boolean(collectionRecord(a.id)));
      if (foundDiff !== 0) return foundDiff;
      return String(a.name || '').localeCompare(String(b.name || ''), 'ru');
    });

  grid.innerHTML = filtered.map((item) => {
    const record = collectionRecord(item.id);
    const rarity = rarityById(item.rarity_id);
    const src = imageSrc(item.image_path);
    const icon = src
      ? `<img class="collection-icon" src="${escapeHtml(src)}" alt="${escapeHtml(item.name || '')}" loading="lazy" onerror="this.classList.add('is-empty');this.removeAttribute('src')">`
      : '<div class="collection-icon is-empty"></div>';
    const count = record ? Number(record.found_count || 0).toLocaleString('ru-RU') : '0';
    const date = record ? formatCollectionDate(record.first_found_at) : '—';
    const bestStack = record ? Math.max(1, Number(record.best_stack || 1)) : 0;
    return `
      <article class="collection-card ${record ? 'is-found' : 'is-locked'}" style="--rarity-color:${(rarity && rarity.color) || '#8f8a7b'}">
        <div class="collection-art">${icon}</div>
        <div class="collection-info">
          <strong>${escapeHtml(item.name || '')}</strong>
          <div>${rarity ? badge(rarity) : '—'}</div>
          <small>${record ? `Найдено: ${count} · первый: ${date}` : 'Не найдено'}</small>
          ${record ? `<small>Лучшая стопка: x${bestStack}</small>` : ''}
        </div>
      </article>
    `;
  }).join('') || '<div class="collection-empty">Ничего не найдено по текущим фильтрам</div>';
}

function setCollectionMode(mode) {
  collectionModeFilter = ['all', 'found', 'missing'].includes(mode) ? mode : 'all';
  renderCollection();
}

function renderFilters() {
  const f = state.settings.filters || {};
  const rh = f.rarity_hidden || {};
  const ih = f.item_hidden || {};

  document.getElementById('filters-rarity').innerHTML = state.rarities
    .map((r) => `<label style="display:flex;align-items:center;gap:6px;background:var(--surface);padding:6px 10px;border:1px solid var(--line);border-radius:8px"><input type="checkbox" ${rh[r.id] ? 'checked' : ''} onchange="toggleRarityFilter('${r.id}',this.checked)"> ${badge(r)}</label>`)
    .join('') || '<i>Нет редкостей</i>';

  const rows = state.items
    .map((i) => {
      const r = rarityById(i.rarity_id);
      return `<tr><td>${i.name}</td><td>${r ? badge(r) : '—'}</td><td><label><input type="checkbox" ${ih[i.id] ? 'checked' : ''} onchange="toggleItemFilter('${i.id}',this.checked)"> скрывать</label></td></tr>`;
    })
    .join('');
  document.getElementById('filters-items-table').innerHTML = `<tr><th>Предмет</th><th>Редкость</th><th>Фильтр</th></tr>${rows}`;
}

function renderSettings() {
  const s = state.settings;
  document.getElementById('set-roll-min').value = s.roll_min;
  document.getElementById('set-roll-max').value = s.roll_max;
  document.getElementById('set-open-price').value = s.open_price;
  document.getElementById('set-base-xp').value = s.levels.base_xp;
  document.getElementById('set-xp-growth').value = s.levels.xp_growth;
  document.getElementById('set-theme').value = (s.appearance && s.appearance.theme) || 'dark';
  const focusChain = s.focus_chain || {};
  document.getElementById('set-chain-break-window').value = focusChain.break_window_minutes ?? 150;
  document.getElementById('set-chain-bonus-every').value = focusChain.bonus_roll_every ?? 2;
  document.getElementById('set-chain-max-bonus').value = focusChain.max_bonus_rolls ?? 5;
  document.getElementById('set-chain-luck-every').value = focusChain.luck_roll_every ?? 3;
  document.getElementById('set-chain-max-luck').value = focusChain.max_luck_rolls ?? 5;
  document.getElementById('set-chain-daily-cap').value = focusChain.daily_chain_bonus_roll_cap ?? 8;
  document.getElementById('set-chain-short-minutes').value = focusChain.short_session_minutes ?? 15;
  document.getElementById('set-chain-short-limit').value = focusChain.short_session_daily_limit ?? 3;
  document.getElementById('set-chain-short-decay').value = focusChain.short_session_decay ?? 0.5;
  document.getElementById('set-chain-long-minutes').value = focusChain.long_session_minutes ?? 45;
  document.getElementById('set-chain-long-bonus').value = focusChain.long_session_bonus_rolls ?? 1;
  document.getElementById('set-chain-deep-minutes').value = focusChain.deep_session_minutes ?? 90;
  document.getElementById('set-chain-deep-bonus').value = focusChain.deep_session_bonus_rolls ?? 2;
  const dropVisuals = s.drop_visuals || {};
  document.getElementById('set-appearance-effect-enabled').checked = dropVisuals.appearance_effect_enabled !== false;
  document.getElementById('set-spawn-cooldown').value = Number.isFinite(dropVisuals.spawn_cooldown_ms) ? dropVisuals.spawn_cooldown_ms : 70;
  document.getElementById('set-drop-bg-image-path').value = dropVisuals.background_image_path || '';
  const brightness = Math.round((Number(dropVisuals.background_brightness ?? 1) || 1) * 100);
  document.getElementById('set-drop-bg-brightness').value = `${Math.min(200, Math.max(20, brightness))}`;
  updateDropBackgroundPreview();
  renderDropEventsTable();
  applyTheme(document.getElementById('set-theme').value);
  showSettingsPane(activeSettingsPane);
}

function renderPresets() {
  const textarea = document.getElementById('preset-json');
  if (!textarea || textarea.value.trim()) return;
  textarea.placeholder = 'Нажмите "Экспортировать текущий пресет" или вставьте JSON пресета сюда';
}

function itemEffectiveWeight(item) {
  const rarity = rarityById(item.rarity_id);
  const rarityWeight = Number((rarity && rarity.weight) || 0);
  const localWeight = Number(item.weight || 0);
  return Math.max(0, rarityWeight) * Math.max(0, localWeight);
}

function marketRow(item) {
  return item && state.market && state.market.prices
    ? state.market.prices[item.id] || null
    : null;
}

function isMarketPriced(item) {
  return Boolean(item && Number(item.market_value_chaos || 0) > 0 && marketRow(item));
}

function formatChaosPrice(value) {
  const price = Number(value || 0);
  if (!Number.isFinite(price) || price <= 0) return '—';
  if (price >= 1000) return `${Math.round(price).toLocaleString('ru-RU')}c`;
  if (price >= 10) return `${price.toFixed(1)}c`;
  if (price >= 1) return `${price.toFixed(2)}c`;
  return `${price.toFixed(4)}c`;
}

function formatMarketChange(row) {
  if (!row) return '—';
  const change = Number(row.last_change || 0) * 100;
  if (!Number.isFinite(change) || Math.abs(change) < 0.005) return '0.00%';
  const sign = change > 0 ? '+' : '';
  return `${sign}${change.toFixed(2)}%`;
}

function calculateShopOffer(targetItem, currencyItem) {
  if (isMarketPriced(targetItem) && isMarketPriced(currencyItem)) {
    const targetMarket = marketRow(targetItem);
    const currencyMarket = marketRow(currencyItem);
    const targetPrice = Number(targetMarket.price_chaos || 0);
    const currencyPrice = Number(currencyMarket.price_chaos || 0);
    if (targetPrice > 0 && currencyPrice > 0) {
      const spread = ((Number(targetMarket.spread || 0.03) + Number(currencyMarket.spread || 0.03)) / 2);
      const baseCost = (targetPrice / currencyPrice) * (1 + 0.15 + spread);
      if (baseCost >= 1) {
        return { minQuantity: 1, bundlePrice: Math.max(1, Math.round(baseCost)), market: true };
      }
      return { minQuantity: Math.max(1, Math.floor(1 / baseCost)), bundlePrice: 1, market: true };
    }
  }

  const targetWeight = itemEffectiveWeight(targetItem);
  const currencyWeight = itemEffectiveWeight(currencyItem);
  if (targetWeight <= 0 || currencyWeight <= 0) return { minQuantity: 1, bundlePrice: 1 };

  // Базовое соотношение без наценки
  const baseCost = currencyWeight / targetWeight;

  if (baseCost >= 1) {
    // Покупаем target за bundlePrice единиц currency
    return { minQuantity: 1, bundlePrice: Math.max(1, Math.round(baseCost)) };
  } else {
    // Покупаем bundlePrice единиц target за 1 currency
    return { minQuantity: Math.max(1, Math.round(1 / baseCost)), bundlePrice: 1 };
  }
}

function renderShop() {
  const currencies = state.items.filter((i) => i.is_currency);
  const currencySelect = document.getElementById('shop-currency');
  const table = document.getElementById('shop-table');
  const meta = document.getElementById('shop-currency-meta');
  if (!currencySelect || !table || !meta) return;

  if (!currencies.length) {
    currencySelect.innerHTML = '';
    meta.textContent = 'Отметьте хотя бы один предмет как "Валюта" во вкладке "Предметы".';
    table.innerHTML = '<tr><td><i>Нет доступной валюты для магазина</i></td></tr>';
    return;
  }

  const previousValue = currencySelect.value;
  currencySelect.innerHTML = currencies.map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join('');
  currencySelect.value = currencies.some((item) => item.id === previousValue) ? previousValue : currencies[0].id;
  const selectedCurrency = currencies.find((item) => item.id === currencySelect.value) || currencies[0];
  const currencyAmount = Number(state.inventory[selectedCurrency.id] || 0);
  const selectedMarket = marketRow(selectedCurrency);
  const marketMeta = selectedMarket
    ? `, рынок: ${formatChaosPrice(selectedMarket.price_chaos)} (${formatMarketChange(selectedMarket)})`
    : '';
  meta.textContent = `Доступно в инвентаре: ${currencyAmount}${marketMeta}`;

  const rows = state.items.map((item) => {
    const offer = calculateShopOffer(item, selectedCurrency);
    const itemRarity = rarityById(item.rarity_id);
    const row = marketRow(item);
    const priceLabel = offer.minQuantity > 1
      ? `${offer.bundlePrice} ${escapeHtml(selectedCurrency.name)} за ${offer.minQuantity} шт. (мин.)`
      : `${offer.bundlePrice} ${escapeHtml(selectedCurrency.name)}`;
    const marketLabel = row
      ? `${formatChaosPrice(row.price_chaos)} <small>vol ${Number(row.volume || 0).toLocaleString('ru-RU')}</small>`
      : '—';
    return `
      <tr>
        <td><span class="item-cell">${itemThumb(item.image_path, item.name)}${escapeHtml(item.name)}</span></td>
        <td>${itemRarity ? badge(itemRarity) : '—'}</td>
        <td class="cell-number">${marketLabel}</td>
        <td class="cell-number">${formatMarketChange(row)}</td>
        <td class="cell-number">${priceLabel}</td>
        <td>
          <div class="row">
            <input id="shop-qty-${item.id}" type="number" min="${offer.minQuantity}" step="${offer.minQuantity}" value="${offer.minQuantity}" style="width:80px">
            <button class="primary" onclick="buyItem('${item.id}')">Купить</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
  table.innerHTML = `<tr><th>Предмет</th><th>Редкость</th><th>Рынок</th><th>Δ</th><th>Цена</th><th>Покупка</th></tr>${rows}`;
}

function dropEventTypeOptions(selectedType = 'normal') {
  return DROP_EVENT_TYPES
    .map(([value, label]) => `<option value="${value}" ${value === selectedType ? 'selected' : ''}>${label}</option>`)
    .join('');
}

function renderDropEventsTable() {
  const events = (state.settings && state.settings.drop_events) || [];
  const rows = events
    .map((event, idx) => `
      <tr data-idx="${idx}" data-id="${escapeHtml(event.id || '')}">
        <td><input data-k="name" value="${escapeHtml(event.name || '')}" placeholder="Название события"></td>
        <td><select data-k="encounter_type">${dropEventTypeOptions(event.encounter_type || 'normal')}</select></td>
        <td><input data-k="weight" type="number" min="0" step="0.1" value="${Number(event.weight || 0)}" style="width:110px"></td>
        <td><input data-k="multiplier" type="number" min="1" step="1" value="${Math.max(1, parseInt(event.multiplier || 1, 10))}" style="width:110px"></td>
        <td><input data-k="rolls" type="number" min="1" step="1" value="${Math.max(1, parseInt(event.rolls || 1, 10))}" style="width:90px"></td>
        <td><input data-k="currency_bias" type="number" min="1" step="0.1" value="${Number(event.currency_bias || 1)}" style="width:90px"></td>
        <td><input data-k="unique_chance" type="number" min="0" max="1" step="0.01" value="${Number(event.unique_chance || 0)}" style="width:90px"></td>
        <td><label><input data-k="currency_only" type="checkbox" ${event.currency_only ? 'checked' : ''}> Валюта</label></td>
        <td><label><input data-k="duplicate_best" type="checkbox" ${event.duplicate_best ? 'checked' : ''}> Дубль</label></td>
        <td><button class="danger" onclick="removeDropEventRow(${idx})">Удалить</button></td>
      </tr>
    `)
    .join('');
  document.getElementById('drop-events-table').innerHTML = `<tr><th>Событие</th><th>Тип</th><th>Вес</th><th>x</th><th>Роллы</th><th>Валюта</th><th>Уник.</th><th>Только</th><th>Лучший</th><th></th></tr>${rows}`;
}

function autoStopItemOptions(selectedId = '') {
  return state.items
    .map((item) => `<option value="${item.id}" ${item.id === selectedId ? 'selected' : ''}>${escapeHtml(item.name)}</option>`)
    .join('');
}

function renderAutoStopConditions() {
  const conditions = (state.settings && state.settings.auto_stop_conditions) || [];
  const rows = conditions.map((condition, idx) => `
    <tr data-idx="${idx}">
      <td><select data-k="item_id">${autoStopItemOptions(condition.item_id)}</select></td>
      <td><input data-k="target_qty" type="number" min="1" value="${Math.max(1, parseInt(condition.target_qty || 1, 10))}" style="width:120px"></td>
      <td><button class="danger" onclick="removeAutoStopCondition(${idx})">Удалить</button></td>
    </tr>
  `).join('');
  document.getElementById('auto-stop-table').innerHTML = `<tr><th>Желаемый предмет</th><th>Количество</th><th></th></tr>${rows || '<tr><td colspan="3"><i>Условия не добавлены</i></td></tr>'}`;
}

function collectAutoStopConditionsRows() {
  return [...document.querySelectorAll('#auto-stop-table tr[data-idx]')].map((tr) => ({
    item_id: tr.querySelector('[data-k="item_id"]').value,
    target_qty: Math.max(1, parseInt(tr.querySelector('[data-k="target_qty"]').value || '1', 10) || 1),
  }));
}

function addAutoStopCondition() {
  if (!state.items.length) {
    setStatus('Добавьте хотя бы один предмет для условий автоостановки', true);
    return;
  }
  state.settings.auto_stop_conditions = state.settings.auto_stop_conditions || [];
  state.settings.auto_stop_conditions.push({
    item_id: state.items[0].id,
    target_qty: 1,
  });
  renderAutoStopConditions();
}

function removeAutoStopCondition(idx) {
  state.settings.auto_stop_conditions = (state.settings.auto_stop_conditions || []).filter((_, i) => i !== idx);
  renderAutoStopConditions();
}

function renderRarityBoosts() {
  const boosts = (state.settings && state.settings.rarity_boosts) || [];
  const rows = boosts.map((boost, idx) => `
    <tr data-idx="${idx}">
      <td><select data-k="rarity_id">${rarityOptions(boost.rarity_id)}</select></td>
      <td><input data-k="percent" type="number" step="0.1" value="${Number(boost.percent || 0)}" style="width:120px"></td>
      <td><button class="danger" onclick="removeRarityBoostRow(${idx})">Удалить</button></td>
    </tr>
  `).join('');
  document.getElementById('boosts-table').innerHTML = `<tr><th>Редкость</th><th>Усиление, %</th><th></th></tr>${rows || '<tr><td colspan="3"><i>Усиления не добавлены</i></td></tr>'}`;
}

function addRarityBoostRow() {
  if (!state.rarities.length) {
    setStatus('Нет редкостей для добавления усиления', true);
    return;
  }
  state.settings.rarity_boosts = state.settings.rarity_boosts || [];
  state.settings.rarity_boosts.push({
    rarity_id: state.rarities[0].id,
    percent: 0,
  });
  renderRarityBoosts();
}

function removeRarityBoostRow(idx) {
  state.settings.rarity_boosts = (state.settings.rarity_boosts || []).filter((_, i) => i !== idx);
  renderRarityBoosts();
}

async function saveRarityBoosts() {
  const boosts = [...document.querySelectorAll('#boosts-table tr[data-idx]')].map((tr) => ({
    rarity_id: tr.querySelector('[data-k="rarity_id"]').value,
    percent: parseFloat(tr.querySelector('[data-k="percent"]').value || '0'),
  }));
  await api('update_settings', { rarity_boosts: boosts });
}

function collectDropEventsRows() {
  return [...document.querySelectorAll('#drop-events-table tr[data-idx]')].map((tr) => ({
    id: tr.dataset.id || '',
    name: tr.querySelector('[data-k="name"]').value || 'Событие',
    encounter_type: tr.querySelector('[data-k="encounter_type"]').value || 'normal',
    weight: parseFloat(tr.querySelector('[data-k="weight"]').value || '0'),
    multiplier: parseInt(tr.querySelector('[data-k="multiplier"]').value || '1', 10),
    rolls: parseInt(tr.querySelector('[data-k="rolls"]').value || '1', 10),
    currency_bias: parseFloat(tr.querySelector('[data-k="currency_bias"]').value || '1'),
    unique_chance: parseFloat(tr.querySelector('[data-k="unique_chance"]').value || '0'),
    currency_only: tr.querySelector('[data-k="currency_only"]').checked,
    duplicate_best: tr.querySelector('[data-k="duplicate_best"]').checked,
  }));
}

function addDropEventRow() {
  state.settings.drop_events = state.settings.drop_events || [];
  state.settings.drop_events.push({
    id: `event-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    name: `Событие ${state.settings.drop_events.length + 1}`,
    encounter_type: 'normal',
    weight: 0,
    multiplier: 2,
    rolls: 1,
    currency_bias: 1,
    unique_chance: 0,
    currency_only: false,
    duplicate_best: false,
  });
  renderDropEventsTable();
}

function removeDropEventRow(idx) {
  state.settings.drop_events = (state.settings.drop_events || []).filter((_, i) => i !== idx);
  if (!state.settings.drop_events.length) {
    state.settings.drop_events = [{ id: 'normal', name: 'Обычная награда', encounter_type: 'normal', weight: 100, multiplier: 1, rolls: 1 }];
  }
  renderDropEventsTable();
}

function renderAll() {
  renderPlayer();
  renderFocus();
  renderItems();
  renderRarities();
  renderRarityGradations();
  renderFilters();
  renderInventory();
  renderCollection();
  renderShop();
  renderRarityBoosts();
  renderSettings();
  renderPresets();
}

function addRarityUpgradeCondition(rarityId) {
  const rarity = state.rarities.find((r) => r.id === rarityId);
  if (!rarity) return;
  rarity.stack_rarity_upgrades = rarity.stack_rarity_upgrades || [];
  rarity.stack_rarity_upgrades.push({
    min_qty: 1,
    target_rarity_id: rarityId,
  });
  renderRarityGradations();
}

function removeRarityUpgradeCondition(rarityId, idx) {
  const rarity = state.rarities.find((r) => r.id === rarityId);
  if (!rarity) return;
  rarity.stack_rarity_upgrades = (rarity.stack_rarity_upgrades || []).filter((_, i) => i !== idx);
  renderRarityGradations();
}

function updateRarityUpgradeMinQty(rarityId, idx, value) {
  const rarity = state.rarities.find((r) => r.id === rarityId);
  if (!rarity) return;
  const minQty = Math.max(1, parseInt(value || '1', 10) || 1);
  rarity.stack_rarity_upgrades = rarity.stack_rarity_upgrades || [];
  if (!rarity.stack_rarity_upgrades[idx]) return;
  rarity.stack_rarity_upgrades[idx].min_qty = minQty;
}

function updateRarityUpgradeTarget(rarityId, idx, targetRarityId) {
  const rarity = state.rarities.find((r) => r.id === rarityId);
  if (!rarity) return;
  rarity.stack_rarity_upgrades = rarity.stack_rarity_upgrades || [];
  if (!rarity.stack_rarity_upgrades[idx]) return;
  rarity.stack_rarity_upgrades[idx].target_rarity_id = targetRarityId;
}

async function api(name, ...args) {
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[name]) {
    setStatus(`API ${name} недоступен`, true);
    return null;
  }
  const result = await window.pywebview.api[name](...args);
  if (!result || result.ok === false) {
    setStatus(result && result.message ? result.message : 'Ошибка запроса', true);
    return result;
  }
  if (result.state) {
    state = result.state;
    renderAll();
  }
  setStatus('OK');
  return result;
}

function dropQuantityTotal(drops) {
  return drops.reduce((total, drop) => total + Math.max(1, parseInt(drop.qty || 1, 10) || 1), 0);
}

function renderOpenSummary(res, drops) {
  const visibleQty = dropQuantityTotal(drops);
  const hiddenQty = Math.max(0, parseInt(res.hidden_results_count || 0, 10) || 0);
  const totalQty = visibleQty + hiddenQty;
  const cardsCount = drops.length;
  const summaryEl = document.getElementById('open-summary');
  if (summaryEl) {
    summaryEl.textContent = hiddenQty
      ? `Выпало ${visibleQty}, скрыто ${hiddenQty}`
      : `Выпало ${visibleQty}`;
  }
  return `
    <div class="drop-summary">
      <span><strong>${totalQty}</strong> предметов в серии</span>
      <small>${cardsCount} карточек показано${hiddenQty ? `, ${hiddenQty} скрыто фильтром` : ''}</small>
    </div>
  `;
}

function renderFocusRewardSummary(res, drops) {
  const reward = res.focus_reward || {};
  const visibleQty = dropQuantityTotal(drops);
  const hiddenQty = Math.max(0, parseInt(res.hidden_results_count || 0, 10) || 0);
  const totalQty = visibleQty + hiddenQty;
  const session = reward.session || {};
  const difficulty = difficultyProfile(reward.difficulty_level || session.difficulty_level || 2);
  const quests = reward.claimed_quests || [];
  const chain = reward.chain || {};
  const antiFarm = reward.anti_farm || {};
  const notes = [];
  if (quests.length) notes.push(`цели дня: ${quests.length}`);
  if (reward.difficulty_bonus_rolls > 0 || reward.difficulty_luck_rolls > 0) {
    const diffBits = [];
    if (reward.difficulty_bonus_rolls > 0) diffBits.push(`+${Number(reward.difficulty_bonus_rolls)} ролл.`);
    if (reward.difficulty_luck_rolls > 0) diffBits.push(`удача +${Number(reward.difficulty_luck_rolls)}`);
    notes.push(`${difficulty.label}: ${diffBits.join(' · ')}`);
  }
  if (reward.long_break_suggested) notes.push('длинный перерыв');
  if (chain.count > 1) notes.push(`цепочка x${Number(chain.count)}`);
  if (chain.bonus_rolls > 0) notes.push(`цепь +${Number(chain.bonus_rolls)} ролл.`);
  if (antiFarm.length_bonus_rolls > 0) notes.push(`длина +${Number(antiFarm.length_bonus_rolls)} ролл.`);
  if (antiFarm.daily_cap_hit) notes.push('дневной лимит цепи');
  if (antiFarm.short_session && Number(antiFarm.short_session_multiplier || 1) < 1) {
    notes.push(`короткая x${Number(antiFarm.short_session_multiplier).toFixed(2)}`);
  }
  if (reward.reward_luck_rolls > 1) notes.push(`удача x${reward.reward_luck_rolls}`);
  const summaryEl = document.getElementById('open-summary');
  if (summaryEl) {
    summaryEl.textContent = `Награда: ${totalQty} предметов`;
  }
  return `
    <div class="drop-summary">
      <span><strong>${Number(session.duration_minutes || 0)}м</strong> фокуса · ${escapeHtml(difficulty.label)}</span>
      <small>${totalQty ? `${totalQty} предметов` : 'каталог предметов пуст'}${notes.length ? ` · ${notes.join(' · ')}` : ''}</small>
    </div>
  `;
}

async function renderFocusReward(res) {
  const drops = res.grouped_visible_results || [];
  const container = document.getElementById('open-results');
  if (!container) return;
  container.innerHTML = `${renderFocusRewardSummary(res, drops)}<div class="drop-floor" id="drop-list"></div>`;
  const listEl = document.getElementById('drop-list');
  applyDropFloorVisuals(listEl);
  const floorWidth = Math.max(320, listEl.clientWidth || container.clientWidth || 320);

  if (!drops.length) {
    listEl.innerHTML = `
      <div class="drop-empty-message">
        <span>Сессия засчитана. Добавьте предметы или импортируйте пресет, чтобы получать лут.</span>
      </div>
    `;
    return;
  }

  const { placements, floorHeight } = createDropLayout(drops, floorWidth);
  listEl.style.height = `${floorHeight}px`;
  const dropVisuals = (state.settings && state.settings.drop_visuals) || {};
  const appearanceEnabled = dropVisuals.appearance_effect_enabled !== false;
  const cooldownMs = Math.max(0, parseInt(dropVisuals.spawn_cooldown_ms ?? 70, 10) || 0);
  for (const drop of drops) {
    const position = placements.shift();
    const wrapClass = appearanceEnabled ? 'drop-card-wrap appear-effect' : 'drop-card-wrap';
    listEl.insertAdjacentHTML('beforeend', dropCardMarkup(drop, { wrapClass, position }));
    if (drop.rarity && drop.rarity.drop_sound) {
      playDropSound(drop.rarity.drop_sound);
    }
    if (cooldownMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, cooldownMs));
    }
  }
}

async function startFocusSession() {
  const duration = parseInt(document.getElementById('focus-duration').value || '25', 10);
  if (!Number.isFinite(duration) || duration < 1) {
    setStatus('Укажите длительность фокуса от 1 минуты', true);
    return;
  }
  const taskTitle = document.getElementById('focus-task').value || '';
  const difficulty = difficultyProfile(document.getElementById('focus-difficulty')?.value || 2);
  const res = await api('start_focus_session', {
    duration_minutes: duration,
    task_title: taskTitle,
    difficulty_level: difficulty.level,
  });
  if (res && res.ok) {
    document.getElementById('open-results').innerHTML = `
      <div class="empty-drop">
        <strong>Фокус запущен</strong>
        <small>Награда будет доступна после завершения таймера.</small>
      </div>
    `;
  }
}

async function cancelFocusSession() {
  const session = activeFocusSession();
  if (!session) return;
  if (!confirm('Отменить текущую фокус-сессию? Награда не будет выдана.')) return;
  stopFocusTimer();
  await api('cancel_focus_session', session.id);
}

async function completeFocusSession() {
  const session = activeFocusSession();
  if (!session || focusCompleting) return;
  focusCompleting = true;
  try {
    const res = await api('complete_focus_session', session.id);
    if (res && res.ok) {
      stopFocusTimer();
      await renderFocusReward(res);
    }
  } finally {
    focusCompleting = false;
    renderFocus();
  }
}

async function openCasesRequest(countOverride = null) {
  const countRaw = countOverride ?? document.getElementById('open-times').value;
  const count = parseInt(countRaw || '1', 10);
  if (!Number.isFinite(count) || count < 1) {
    setStatus('Укажите количество кейсов (минимум 1)', true);
    return false;
  }

  const res = await api('open_case', count);
  if (!res || !res.ok) return;
  return res;
}

async function openCasesAndRender(countOverride = null) {
  const res = await openCasesRequest(countOverride);
  if (!res || !res.ok) return null;

  const drops = res.grouped_visible_results || [];
  const container = document.getElementById('open-results');
  container.innerHTML = `${renderOpenSummary(res, drops)}<div class="drop-floor" id="drop-list"></div>`;
  const listEl = document.getElementById('drop-list');
  applyDropFloorVisuals(listEl);
  const floorWidth = Math.max(320, listEl.clientWidth || container.clientWidth || 320);

  if (!drops.length) {
    listEl.innerHTML = '<div class="drop-empty-message"><span>Все выпадения скрыты фильтром</span></div>';
  } else {
    const { placements, floorHeight } = createDropLayout(drops, floorWidth);
    listEl.style.height = `${floorHeight}px`;
    const dropVisuals = (state.settings && state.settings.drop_visuals) || {};
    const appearanceEnabled = dropVisuals.appearance_effect_enabled !== false;
    const cooldownMs = Math.max(0, parseInt(dropVisuals.spawn_cooldown_ms ?? 70, 10) || 0);
    for (const drop of drops) {
      const x = drop;
      const position = placements.shift();
      const wrapClass = appearanceEnabled ? 'drop-card-wrap appear-effect' : 'drop-card-wrap';
      const cardHtml = dropCardMarkup(x, { wrapClass, position });
      listEl.insertAdjacentHTML('beforeend', cardHtml);
      if (x.rarity && x.rarity.drop_sound) {
        playDropSound(x.rarity.drop_sound);
      }
      if (cooldownMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, cooldownMs));
      }
    }
  }

  return res;
}

async function openCases(countOverride = null) {
  return openCasesAndRender(countOverride);
}

function updateAutoOpenUi() {
  const isRunning = autoOpenTimerId !== null;
  const startEl = document.getElementById('auto-open-start');
  const stopEl = document.getElementById('auto-open-stop');
  const statusEl = document.getElementById('auto-open-status');
  if (!startEl || !stopEl || !statusEl) return;
  startEl.disabled = isRunning;
  stopEl.disabled = !isRunning;
  statusEl.textContent = isRunning ? 'Таймер активен' : 'Таймер не активен';
  const openLayout = document.getElementById('open-layout');
  if (openLayout) {
    openLayout.classList.toggle('auto-running', isRunning);
  }
}

function stopAutoOpen() {
  if (autoOpenTimerId !== null) {
    clearInterval(autoOpenTimerId);
    autoOpenTimerId = null;
  }
  autoOpenBusy = false;
  autoOpenStartInventoryByItem = {};
  updateAutoOpenUi();
}

function checkAutoStopReached() {
  const conditions = collectAutoStopConditionsRows();
  for (const condition of conditions) {
    const item = state.items.find((x) => x.id === condition.item_id);
    const startQty = Number(autoOpenStartInventoryByItem[condition.item_id] || 0);
    const nowQty = Number((state.inventory && state.inventory[condition.item_id]) || 0);
    const currentQty = Math.max(0, nowQty - startQty);
    if (currentQty >= condition.target_qty) {
      return {
        hit: true,
        condition,
        itemName: item ? item.name : condition.item_id,
        currentQty,
      };
    }
  }
  return { hit: false };
}

async function startAutoOpen() {
  if (autoOpenTimerId !== null) return;
  const interval = parseInt(document.getElementById('open-interval').value || '1000', 10);
  const count = parseInt(document.getElementById('open-times').value || '1', 10);

  if (!Number.isFinite(interval) || interval < 100) {
    setStatus('Интервал должен быть не меньше 100 мс', true);
    return;
  }
  if (!Number.isFinite(count) || count < 1) {
    setStatus('Укажите количество кейсов (минимум 1)', true);
    return;
  }
  const autoStopConditions = collectAutoStopConditionsRows();
  const saveConditionsResult = await api('update_settings', { auto_stop_conditions: autoStopConditions });
  if (!saveConditionsResult || !saveConditionsResult.ok) {
    return;
  }

  const tick = async () => {
    if (autoOpenBusy) return;
    autoOpenBusy = true;
    try {
      const res = await openCasesAndRender(count);
      if (!res || !res.ok) return;
      const stopCheck = checkAutoStopReached();
      if (stopCheck.hit) {
        stopAutoOpen();
        setStatus(`Автооткрытие остановлено: ${stopCheck.itemName} x${stopCheck.currentQty}`, false);
      }
    } finally {
      autoOpenBusy = false;
    }
  };

  autoOpenStartInventoryByItem = { ...(state.inventory || {}) };
  autoOpenTimerId = setInterval(tick, interval);
  updateAutoOpenUi();
  tick();
}

async function addItem() {
  await api('add_item', {
    name: document.getElementById('item-name').value,
    rarity_id: document.getElementById('item-rarity').value,
    weight: parseFloat(document.getElementById('item-weight').value || '1'),
    image_path: document.getElementById('item-image').value,
    description: document.getElementById('item-description').value,
    is_currency: false,
  });
}

async function delItem(id) {
  if (confirm('Удалить предмет?')) await api('delete_item', id);
}

async function saveItemsBulk() {
  const rows = [...document.querySelectorAll('#items-table tr[data-id]')].map((tr) => {
    const obj = { id: tr.dataset.id };
    for (const el of tr.querySelectorAll('[data-k]')) {
      obj[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value;
    }
    return obj;
  });
  await api('update_items_bulk', rows);
}

async function buyItem(itemId) {
  const currencyId = document.getElementById('shop-currency').value;
  if (!currencyId) {
    setStatus('Выберите валюту', true);
    return;
  }
  const qtyEl = document.getElementById(`shop-qty-${itemId}`);
  const quantity = parseInt((qtyEl && qtyEl.value) || '1', 10);
  if (!Number.isFinite(quantity) || quantity < 1) {
    setStatus('Количество покупки должно быть не меньше 1', true);
    return;
  }
  await api('purchase_item', itemId, currencyId, quantity);
}

async function addRarity() {
  await api('add_rarity', {
    name: document.getElementById('rarity-name').value,
    weight: parseFloat(document.getElementById('rarity-weight').value || '1'),
    color: document.getElementById('rarity-color').value,
    drop_bg_color: document.getElementById('rarity-drop-bg-color').value,
    drop_text_color: document.getElementById('rarity-drop-text-color').value,
    drop_border_color: document.getElementById('rarity-drop-border-color').value,
    drop_box_width: parseInt(document.getElementById('rarity-drop-box-width').value || '260', 10),
    drop_box_height: parseInt(document.getElementById('rarity-drop-box-height').value || '60', 10),
    drop_font_size: parseInt(document.getElementById('rarity-drop-font-size').value || '18', 10),
    stack_max_size: parseInt(document.getElementById('rarity-stack-max-size').value || '10', 10),
    stack_display_max: parseInt(document.getElementById('rarity-stack-display-max').value || '99', 10),
    drop_sound: document.getElementById('rarity-sound').value,
  });
}

async function delRarity(id) {
  if (confirm('Удалить редкость?')) await api('delete_rarity', id);
}

async function consumeItem(id) {
  const amountEl = document.getElementById(`consume-${id}`);
  const amount = parseInt((amountEl && amountEl.value) || '1', 10);
  if (!Number.isFinite(amount) || amount < 1) {
    setStatus('Введите корректное количество для списания (минимум 1)', true);
    return;
  }
  await api('adjust_inventory', id, -amount);
}

async function clearInventory() {
  if (!confirm('Очистить весь инвентарь? Это действие нельзя отменить.')) return;
  await api('clear_inventory');
}

async function clearCollection() {
  if (!confirm('Сбросить альбом предметов? Инвентарь останется без изменений.')) return;
  await api('clear_collection');
}

async function normalizeRangesWithConfirm() {
  if (!confirm('Выставить одинаковые веса для всех редкостей? Текущие веса будут перезаписаны.')) return;
  await api('normalize_rarity_ranges');
}

async function saveRarityBulk() {
  const rows = [...document.querySelectorAll('#rarities-table tr[data-id]')].map((tr) => {
    const obj = { id: tr.dataset.id };
    for (const el of tr.querySelectorAll('[data-k]')) obj[el.dataset.k] = el.value;
    return obj;
  });
  await api('update_rarities_bulk', rows);
}

async function saveRarityGradations() {
  const rows = state.rarities.map((rarity) => ({
    id: rarity.id,
    stack_rarity_upgrades: (rarity.stack_rarity_upgrades || []).map((rule) => ({
      min_qty: Math.max(1, parseInt(rule.min_qty || 1, 10) || 1),
      target_rarity_id: rule.target_rarity_id,
    })),
  }));
  await api('update_rarities_bulk', rows);
}

async function toggleRarityFilter(id, hidden) {
  await api('set_filter_rarity', id, hidden);
}

async function toggleItemFilter(id, hidden) {
  await api('set_filter_item', id, hidden);
}

async function saveSettings() {
  await api('update_settings', {
    roll_min: parseFloat(document.getElementById('set-roll-min').value),
    roll_max: parseFloat(document.getElementById('set-roll-max').value),
    open_price: parseFloat(document.getElementById('set-open-price').value),
    appearance: { theme: document.getElementById('set-theme').value },
    drop_visuals: {
      spawn_cooldown_ms: parseInt(document.getElementById('set-spawn-cooldown').value || '70', 10),
      appearance_effect_enabled: document.getElementById('set-appearance-effect-enabled').checked,
      background_image_path: document.getElementById('set-drop-bg-image-path').value,
      background_brightness: parseInt(document.getElementById('set-drop-bg-brightness').value || '100', 10) / 100,
    },
    drop_events: collectDropEventsRows(),
    levels: {
      base_xp: parseInt(document.getElementById('set-base-xp').value, 10),
      xp_growth: parseFloat(document.getElementById('set-xp-growth').value),
    },
    focus_chain: {
      break_window_minutes: parseInt(document.getElementById('set-chain-break-window').value || '150', 10),
      bonus_roll_every: parseInt(document.getElementById('set-chain-bonus-every').value || '2', 10),
      max_bonus_rolls: parseInt(document.getElementById('set-chain-max-bonus').value || '5', 10),
      luck_roll_every: parseInt(document.getElementById('set-chain-luck-every').value || '3', 10),
      max_luck_rolls: parseInt(document.getElementById('set-chain-max-luck').value || '5', 10),
      daily_chain_bonus_roll_cap: parseInt(document.getElementById('set-chain-daily-cap').value || '8', 10),
      short_session_minutes: parseInt(document.getElementById('set-chain-short-minutes').value || '15', 10),
      short_session_daily_limit: parseInt(document.getElementById('set-chain-short-limit').value || '3', 10),
      short_session_decay: parseFloat(document.getElementById('set-chain-short-decay').value || '0.5'),
      long_session_minutes: parseInt(document.getElementById('set-chain-long-minutes').value || '45', 10),
      long_session_bonus_rolls: parseInt(document.getElementById('set-chain-long-bonus').value || '1', 10),
      deep_session_minutes: parseInt(document.getElementById('set-chain-deep-minutes').value || '90', 10),
      deep_session_bonus_rolls: parseInt(document.getElementById('set-chain-deep-bonus').value || '2', 10),
    },
  });
}

async function pickDropBackgroundImage() {
  const res = await api('pick_image_file');
  if (!res || !res.ok) return;
  document.getElementById('set-drop-bg-image-path').value = res.path || '';
}

async function pickSoundFile() {
  const res = await api('pick_sound_file');
  if (!res || !res.ok) return '';
  return res.path || '';
}

async function pickSoundForNewRarity() {
  const path = await pickSoundFile();
  if (path) document.getElementById('rarity-sound').value = path;
}

async function pickSoundForRow(rarityId) {
  const path = await pickSoundFile();
  if (!path) return;
  const row = document.querySelector(`#rarities-table tr[data-id="${rarityId}"]`);
  if (!row) return;
  const input = row.querySelector('input[data-k="drop_sound"]');
  if (input) input.value = path;
}

async function toggleTheme() {
  const current = (state.settings.appearance && state.settings.appearance.theme) || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  await api('update_settings', { appearance: { theme: next } });
}

async function exportPreset() {
  const res = await api('export_preset');
  if (!res || !res.ok) return;
  const textarea = document.getElementById('preset-json');
  if (textarea) {
    textarea.value = JSON.stringify(res.preset, null, 2);
  }
}

async function importPreset() {
  const textarea = document.getElementById('preset-json');
  if (!textarea) return;
  let preset = null;
  try {
    preset = JSON.parse(textarea.value || '{}');
  } catch (_err) {
    setStatus('JSON пресета поврежден', true);
    return;
  }
  if (!confirm('Импортировать пресет? Каталог предметов и редкостей будет заменен.')) return;
  await api('import_preset', preset);
}

window.addEventListener('pywebviewready', async () => {
  tab('open');
  const res = await window.pywebview.api.get_state();
  if (res && res.ok) {
    state = res.state;
    renderAll();
  }
  const brightnessInput = document.getElementById('set-drop-bg-brightness');
  if (brightnessInput) {
    brightnessInput.addEventListener('input', updateDropBackgroundPreview);
  }
  const difficultyInput = document.getElementById('focus-difficulty');
  if (difficultyInput) {
    difficultyInput.addEventListener('input', renderDifficultyContract);
  }
  if (focusResetTimerId === null) {
    focusResetTimerId = setInterval(renderFocusResetTimers, 1000);
  }
  updateAutoOpenUi();
  renderFocus();
});
