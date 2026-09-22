// The one-off upload form. Resizing happens here in the browser, so nothing
// server-side has to carry an image library: each photo becomes an original,
// a full size and a thumbnail, all three PUT straight to S3 with the
// presigned URLs the API hands out. Only then is the record posted.

import { API_BASE, SITE_TITLE } from './config.js';

const THUMB_MAX = 600;
const FULL_MAX = 2000;
const ORIG_MAX = 3200;     // the "original" is still capped -- a phone photo
                           // straight off the camera is not worth the storage
const JPEG_QUALITY = 0.85;
const MAX_PHOTOS = 24;

const form = document.getElementById('add-form');
const titleInput = document.getElementById('title');
const captionInput = document.getElementById('caption');
const dateInput = document.getElementById('date');
const tagsInput = document.getElementById('tags');
const fileInput = document.getElementById('files');
const dropZone = document.getElementById('drop-zone');
const previews = document.getElementById('previews');
const submit = document.getElementById('submit');
const progress = document.getElementById('progress');
const error = document.getElementById('error');

let chosen = [];

// The site's name lives in .env, not in the markup.
if (SITE_TITLE) {
  document.title = 'Add something - ' + SITE_TITLE;
  const home = document.querySelector('.home-link');
  if (home) home.textContent = SITE_TITLE;
}

// ------------------------------------------------------------------- picking

function refreshPreviews() {
  previews.textContent = '';
  chosen.forEach((file, index) => {
    const figure = document.createElement('figure');
    const img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = '';
    img.addEventListener('load', () => URL.revokeObjectURL(img.src), { once: true });
    const caption = document.createElement('figcaption');
    caption.textContent = index === 0 ? 'cover' : String(index + 1);
    figure.append(img, caption);
    previews.appendChild(figure);
  });
}

function addFiles(list) {
  const images = [...list].filter((file) => file.type.startsWith('image/'));
  chosen = chosen.concat(images).slice(0, MAX_PHOTOS);
  refreshPreviews();
}

fileInput.addEventListener('change', () => addFiles(fileInput.files));

for (const type of ['dragenter', 'dragover']) {
  dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.add('over');
  });
}
for (const type of ['dragleave', 'drop']) {
  dropZone.addEventListener(type, (event) => {
    event.preventDefault();
    dropZone.classList.remove('over');
  });
}
dropZone.addEventListener('drop', (event) => {
  if (event.dataTransfer && event.dataTransfer.files) addFiles(event.dataTransfer.files);
});

// ------------------------------------------------------------------ resizing

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('That file is not an image the browser can read.'));
    };
    // Decoding through an <img> rather than createImageBitmap means the
    // browser applies the EXIF orientation itself, so a phone photo taken
    // sideways is not stored sideways.
    img.src = url;
  });
}

function resize(img, maxEdge) {
  const scale = Math.min(1, maxEdge / Math.max(img.naturalWidth, img.naturalHeight));
  const width = Math.max(1, Math.round(img.naturalWidth * scale));
  const height = Math.max(1, Math.round(img.naturalHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(img, 0, 0, width, height);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve({ blob, width, height }) : reject(new Error('Could not resize that photo.'))),
      'image/jpeg',
      JPEG_QUALITY,
    );
  });
}

async function put(url, blob) {
  const response = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'image/jpeg' },
    body: blob,
  });
  if (!response.ok) throw new Error(`Upload failed (${response.status}).`);
}

// --------------------------------------------------------------------- slug

function slugify(text) {
  return text
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

function itemId(title, date) {
  const year = (date || '').slice(0, 4);
  const base = slugify(title) || 'item';
  const stem = year ? `${base}-${year}` : base;
  // A short suffix keeps two shirts called "school shirt" from colliding.
  return `${stem}-${Math.random().toString(36).slice(2, 6)}`;
}

// ------------------------------------------------------------------- submit

async function api(path, options) {
  const response = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
  return payload;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';

  if (!chosen.length) {
    error.textContent = 'Pick at least one photo.';
    return;
  }

  submit.disabled = true;
  const id = itemId(titleInput.value.trim(), dateInput.value.trim());

  try {
    progress.textContent = 'Getting ready...';
    const { uploads } = await api('/upload-url', {
      method: 'POST',
      body: JSON.stringify({ itemId: id, count: chosen.length }),
    });

    const photos = [];
    for (let index = 0; index < chosen.length; index += 1) {
      progress.textContent = `Photo ${index + 1} of ${chosen.length}...`;
      const img = await loadImage(chosen[index]);
      const [orig, full, thumb] = await Promise.all([
        resize(img, ORIG_MAX),
        resize(img, FULL_MAX),
        resize(img, THUMB_MAX),
      ]);
      const slot = uploads[index];
      await Promise.all([
        put(slot.orig, orig.blob),
        put(slot.full, full.blob),
        put(slot.thumb, thumb.blob),
      ]);
      photos.push({ id: slot.id, w: thumb.width, h: thumb.height });
    }

    progress.textContent = 'Filing it...';
    await api('/items', {
      method: 'POST',
      body: JSON.stringify({
        id,
        title: titleInput.value.trim(),
        caption: captionInput.value.trim(),
        date: dateInput.value.trim(),
        tags: tagsInput.value,
        photos,
      }),
    });

    progress.textContent = '';
    window.location.href = '/';
  } catch (err) {
    error.textContent = err.message || 'Something went wrong.';
    progress.textContent = '';
    submit.disabled = false;
  }
});
