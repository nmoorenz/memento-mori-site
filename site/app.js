// The wall of mementos: load the manifest, filter it, lay it out in columns,
// and open a lightbox that walks every photo of every visible item in order.

import { MANIFEST_URL, SITE_TITLE } from './config.js';

const grid = document.getElementById('grid');
const statusEl = document.getElementById('status');
const countEl = document.getElementById('item-count');
const sortSelect = document.getElementById('sort-select');
const searchInput = document.getElementById('search-input');
const whenSelect = document.getElementById('when-select');
const tagButton = document.getElementById('tag-button');
const tagMenu = document.getElementById('tag-menu');
const clearButton = document.getElementById('clear-filters');

const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-img');
const lightboxTitle = document.getElementById('lightbox-title');
const lightboxDate = document.getElementById('lightbox-date');
const lightboxCaption = document.getElementById('lightbox-caption');
const lightboxTags = document.getElementById('lightbox-tags');
const lightboxCount = document.getElementById('lightbox-count');

let items = [];
let visible = [];
let frames = [];        // flattened [{item, photo, index, total}] for the lightbox
let frameIndex = -1;

const state = {
  sort: 'date-desc',
  search: '',
  // Sort and When hold one value each; tags hold any number, ANDed together.
  tags: new Set(),
  year: '',
};

// ---------------------------------------------------------------------- util

function setStatus(message) {
  statusEl.textContent = message || '';
  statusEl.hidden = !message;
}

function yearOf(date) {
  const year = (date || '').slice(0, 4);
  return /^\d{4}$/.test(year) ? year : '';
}

function dateDisplay(item) {
  return (item.date || '').slice(0, 4);
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// ------------------------------------------------------------------ filters

function tagCounts(pool) {
  const counts = new Map();
  for (const item of pool) {
    for (const tag of item.tags || []) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  // Most-used first, then alphabetical, so the tags that earn their place
  // sit at the top of a freeform list.
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function yearCounts(pool) {
  const counts = new Map();
  for (const item of pool) {
    const year = yearOf(item.date);
    if (year) counts.set(year, (counts.get(year) || 0) + 1);
  }
  // Newest year first, matching the default sort.
  return [...counts.entries()].sort((a, b) => b[0].localeCompare(a[0]));
}

// Fill a dropdown from [[value, count]], keeping the current choice if it is
// still one of the options and falling back to "any" if the data moved on.
function fillSelect(select, entries, anyLabel, chosen) {
  const keep = entries.some(([value]) => value === chosen) ? chosen : '';
  select.textContent = '';

  const any = document.createElement('option');
  any.value = '';
  any.textContent = anyLabel;
  select.appendChild(any);

  for (const [value, count] of entries) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = `${value} (${count})`;
    select.appendChild(option);
  }

  select.value = keep;
  return keep;
}

function tagButtonLabel() {
  if (!state.tags.size) return 'All tags';
  if (state.tags.size === 1) return [...state.tags][0];
  return `${state.tags.size} tags`;
}

function renderTagMenu() {
  const entries = tagCounts(items);
  // Drop any selection the data no longer has, so a stale tag cannot hide
  // everything with no way to see why.
  for (const tag of [...state.tags]) {
    if (!entries.some(([value]) => value === tag)) state.tags.delete(tag);
  }

  tagMenu.textContent = '';
  for (const [value, count] of entries) {
    const option = document.createElement('label');
    option.className = 'dropdown-option';

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = value;
    box.checked = state.tags.has(value);
    box.addEventListener('change', () => {
      if (box.checked) state.tags.add(value);
      else state.tags.delete(value);
      tagButton.textContent = tagButtonLabel();
      render();
    });

    const name = document.createElement('span');
    name.textContent = value;

    const badge = document.createElement('span');
    badge.className = 'count';
    badge.textContent = count;

    option.append(box, name, badge);
    tagMenu.appendChild(option);
  }

  tagButton.textContent = tagButtonLabel();
  tagButton.disabled = entries.length === 0;
}

function openTagMenu(open) {
  tagMenu.hidden = !open;
  tagButton.setAttribute('aria-expanded', String(open));
}

function renderFilters() {
  state.year = fillSelect(whenSelect, yearCounts(items), 'Any year', state.year);
  renderTagMenu();
  clearButton.hidden = !state.tags.size && !state.year && !state.search;
}

function matches(item) {
  if (state.year && yearOf(item.date) !== state.year) return false;
  // Tags are AND: picking two narrows, it does not widen.
  for (const tag of state.tags) {
    if (!(item.tags || []).includes(tag)) return false;
  }
  if (state.search) {
    const haystack = [item.title, item.caption, ...(item.tags || [])].join(' ').toLowerCase();
    if (!haystack.includes(state.search)) return false;
  }
  return true;
}

function sorted(pool) {
  const copy = [...pool];
  switch (state.sort) {
    case 'date-asc':
      return copy.sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999'));
    case 'title':
      return copy.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    case 'added':
      return copy.sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    case 'date-desc':
    default:
      return copy.sort((a, b) => (b.date || '0000').localeCompare(a.date || '0000'));
  }
}

// -------------------------------------------------------------------- cards

function card(item, position) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'item-card';

  const photo = (item.photos || [])[0];
  if (photo) {
    const cover = document.createElement('div');
    cover.className = 'item-cover';

    const img = document.createElement('img');
    img.src = photo.thumb;
    img.alt = item.title || '';
    img.loading = 'lazy';
    // Reserving the right box before the image arrives is what stops the
    // columns from jumping around as they fill in.
    if (photo.w && photo.h) {
      img.width = photo.w;
      img.height = photo.h;
    }
    cover.appendChild(img);

    if ((item.photos || []).length > 1) {
      const badge = document.createElement('span');
      badge.className = 'item-more';
      badge.textContent = `+${item.photos.length - 1}`;
      cover.appendChild(badge);
    }
    button.appendChild(cover);
  }

  const body = document.createElement('div');
  body.className = 'item-body';

  const title = document.createElement('h2');
  title.textContent = item.title || item.id;
  body.appendChild(title);

  const when = dateDisplay(item);
  if (when) {
    const dateEl = document.createElement('p');
    dateEl.className = 'item-date';
    dateEl.textContent = when;
    body.appendChild(dateEl);
  }

  if (item.caption) {
    const caption = document.createElement('p');
    caption.className = 'item-caption';
    caption.textContent = item.caption;
    body.appendChild(caption);
  }

  if ((item.tags || []).length) {
    const tags = document.createElement('div');
    tags.className = 'item-tags';
    for (const tag of item.tags) {
      const span = document.createElement('span');
      span.className = 'tag';
      span.textContent = tag;
      tags.appendChild(span);
    }
    body.appendChild(tags);
  }

  button.appendChild(body);
  button.addEventListener('click', () => openLightbox(position));
  return button;
}

// How many columns the wall gets at this width. Kept here rather than in a
// media query because app.js is the thing that fills them.
function columnCount() {
  const width = document.documentElement.clientWidth;
  if (width <= 520) return 1;
  if (width <= 800) return 2;
  if (width <= 1150) return 3;
  return 4;
}

// Each card goes into whichever column is currently shortest, so the order
// still reads left-to-right and the columns still come out level. Heights are
// estimated from the cover's aspect ratio plus a rough allowance for the text
// -- close enough to pack well, and it needs no layout measurement.
function layout() {
  const columns = columnCount();
  grid.textContent = '';

  const elements = [];
  const heights = new Array(columns).fill(0);
  for (let index = 0; index < columns; index += 1) {
    const column = document.createElement('div');
    column.className = 'masonry-column';
    elements.push(column);
    grid.appendChild(column);
  }

  visible.forEach((item) => {
    const first = frames.findIndex((frame) => frame.item === item);
    const photo = (item.photos || [])[0];
    const ratio = photo && photo.w && photo.h ? photo.h / photo.w : 0.75;
    const text = 2.6 + (item.caption ? Math.min(4, item.caption.length / 55) : 0)
      + ((item.tags || []).length ? 1.4 : 0);

    let shortest = 0;
    for (let index = 1; index < columns; index += 1) {
      if (heights[index] < heights[shortest]) shortest = index;
    }
    elements[shortest].appendChild(card(item, first));
    heights[shortest] += ratio * 10 + text;
  });
}

function render() {
  visible = sorted(items.filter(matches));

  frames = [];
  visible.forEach((item) => {
    const photos = item.photos || [];
    photos.forEach((photo, index) => {
      frames.push({ item, photo, index, total: photos.length });
    });
  });

  layout();

  const total = items.length;
  countEl.textContent = visible.length === total
    ? plural(total, 'thing', 'things')
    : `${visible.length} of ${plural(total, 'thing', 'things')}`;

  setStatus(visible.length ? '' : (total ? 'Nothing matches those filters.' : 'Nothing here yet.'));
  clearButton.hidden = !state.tags.size && !state.year && !state.search;
}

// ----------------------------------------------------------------- lightbox

function showFrame(index) {
  if (index < 0 || index >= frames.length) return;
  frameIndex = index;
  const frame = frames[index];

  lightboxImg.src = frame.photo.full;
  lightboxImg.alt = frame.item.title || '';
  lightboxTitle.textContent = frame.item.title || frame.item.id;
  const when = dateDisplay(frame.item);
  lightboxDate.textContent = when;
  lightboxDate.hidden = !when;
  lightboxCaption.textContent = frame.item.caption || '';
  lightboxCaption.hidden = !frame.item.caption;

  lightboxTags.textContent = '';
  for (const tag of frame.item.tags || []) {
    const span = document.createElement('span');
    span.className = 'tag';
    span.textContent = tag;
    lightboxTags.appendChild(span);
  }

  lightboxCount.textContent = frame.total > 1 ? `Photo ${frame.index + 1} of ${frame.total}` : '';
}

function openLightbox(index) {
  if (index < 0 || !frames.length) return;
  lightbox.hidden = false;
  document.body.style.overflow = 'hidden';
  showFrame(index);
}

function closeLightbox() {
  lightbox.hidden = true;
  lightboxImg.removeAttribute('src');
  document.body.style.overflow = '';
  frameIndex = -1;
}

function step(delta) {
  const next = frameIndex + delta;
  if (next >= 0 && next < frames.length) showFrame(next);
}

document.getElementById('lightbox-close').addEventListener('click', closeLightbox);
document.getElementById('lightbox-prev').addEventListener('click', () => step(-1));
document.getElementById('lightbox-next').addEventListener('click', () => step(1));
lightbox.addEventListener('click', (event) => {
  if (event.target === lightbox || event.target.classList.contains('lightbox-image')) closeLightbox();
});

document.addEventListener('keydown', (event) => {
  if (lightbox.hidden) return;
  if (event.key === 'Escape') closeLightbox();
  if (event.key === 'ArrowLeft') step(-1);
  if (event.key === 'ArrowRight') step(1);
});

// ------------------------------------------------------------------ controls

sortSelect.addEventListener('change', () => {
  state.sort = sortSelect.value;
  render();
});

whenSelect.addEventListener('change', () => {
  state.year = whenSelect.value;
  render();
});

tagButton.addEventListener('click', (event) => {
  event.stopPropagation();
  openTagMenu(tagMenu.hidden);
});

tagMenu.addEventListener('click', (event) => event.stopPropagation());

document.addEventListener('click', () => openTagMenu(false));

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !tagMenu.hidden) {
    openTagMenu(false);
    tagButton.focus();
  }
});

let searchTimer = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = searchInput.value.trim().toLowerCase();
    render();
  }, 150);
});

let resizeTimer = null;
let lastColumns = columnCount();
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    // Only a change in column count needs the cards moved.
    const columns = columnCount();
    if (columns !== lastColumns) {
      lastColumns = columns;
      layout();
    }
  }, 150);
});

clearButton.addEventListener('click', () => {
  state.tags.clear();
  state.year = '';
  state.search = '';
  searchInput.value = '';
  whenSelect.value = '';
  openTagMenu(false);
  renderTagMenu();
  render();
});

// ---------------------------------------------------------------------- boot

// The site's name lives in .env, not in the markup, so the repo carries no
// particular site's identity.
function applyTitle() {
  if (!SITE_TITLE) return;
  document.title = SITE_TITLE;
  const home = document.querySelector('.home-link');
  if (home) home.textContent = SITE_TITLE;
}

async function boot() {
  applyTitle();
  setStatus('Loading...');
  try {
    const response = await fetch(MANIFEST_URL, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`manifest ${response.status}`);
    const manifest = await response.json();
    items = (manifest.items || []).filter((item) => (item.photos || []).length);
  } catch (err) {
    setStatus('Could not load the collection. Reload to try again.');
    return;
  }
  setStatus('');
  renderFilters();
  render();
}

boot();
