# site/

The frontend. Plain ES modules and CSS, no build step and no dependencies.

| File | What it is |
| --- | --- |
| `index.html`, `app.js` | The wall: filters, sorting, search, masonry layout, lightbox |
| `add.html`, `add.js` | The upload form |
| `login.html` | The password page. Standalone — no imports, no module |
| `style.css` | One `:root` block holds the whole palette |
| `config.js` | Placeholders. The deployed copy is generated into `build/` |

## Previewing

```bash
python scripts/sample_data.py
cd site && python -m http.server 8000
```

`config.js` points `MANIFEST_URL` at `./manifest.json`, which
`sample_data.py` writes from [`example/`](../example/README.md) alongside the
derivatives in `./sample-photos/`. Both are gitignored. The password page and the upload form need the deployed
backend; the wall, the filters and the lightbox all work locally.

## config.js

```js
export const MANIFEST_URL = "./manifest.json";  // "/data/manifest.json" deployed
export const API_BASE = "/api";
export const SITE_TITLE = "Mementos";           // from .env SITE_TITLE
```

The committed copy is never given real values. `scripts/deploy_site.py` writes
`build/site/config.js` with the deployed ones and uploads that.

`SITE_TITLE` is applied at runtime: `app.js` and `add.js` set
`document.title` and the header link from it, so the markup carries no
particular site's name.

## The wall

`app.js` fetches the manifest and renders every item that has at least one
photo.

Layout is real columns filled by `layout()`, not CSS `column-count`: it builds
one `div.masonry-column` per column and appends each card to whichever is
currently shortest, estimating height from the cover's aspect ratio plus an
allowance for the text. Reading order stays left to right. Columns are 4 / 3 /
2 / 1 at 1150px, 800px and 520px, and a resize relays only when the count
changes. Each `img` carries the `w`/`h` from the manifest so a card reserves
its space before the image loads.

Sort, When and Tags are dropdowns, all three built from the data itself.
When lists the year of each item's date, newest first, with "Any year" to
clear it — one choice.

Tags is a button that opens a list of checkboxes rather than a `<select>`,
since more than one can be picked and a native multiple select is a
ctrl-click list box. Tags are ANDed: picking two narrows, it does not widen.
The button reads "All tags", the tag name, or "N tags". The menu stays open
while you tick, and closes on Escape or a click outside. Options are the tags
the items actually use, most-used first, each with its count.

Search matches title, caption and tags.

The lightbox walks a flat list of every photo of every visible item, so the
arrow keys carry on past the end of an item and into the next. Escape closes;
clicking the backdrop closes.

## The upload form

`add.js` resizes each photo in the browser with a canvas, producing a capped
original, a 2000px full size and a 600px thumbnail. Decoding through an `<img>`
means the browser applies EXIF orientation itself. All three sizes go straight
to S3 with presigned PUT URLs, then the record is posted to the API.

## The password page

`login.html` is one of the two assets CloudFront serves without signed
cookies, and the page CloudFront substitutes for a 403, so it stands alone: no
module, no imports, nothing but `style.css`. It shows no site name. It posts
to `/auth/login` and reloads on success.

## Palette

Every colour is a custom property in the `:root` block at the top of
`style.css` — page, cards, rules, and the lightbox surface. Swapping palettes
means replacing that block. `--veil` is separate because the `+N` badge sits
on top of a photo rather than on the palette.
