# example/

A committed set of items from Ready Player One, with placeholder photos, in
exactly the layout [`photos/`](../photos/README.md) expects. Nothing here
describes anything real — the images are generated shapes, not photographs.

```
example/
    items.csv
    IMG_4821.JPG  IMG_4822.JPG  IMG_4823.JPG
    IMG_5090.JPG  IMG_5091.JPG
    DSC_0412.jpg  DSC_0413.jpg
    scan_0007.jpg  scan_0012.jpg
```

The filenames are deliberately camera- and scanner-shaped: nothing renames
your photos, so the csv's `photos` column is what ties a file to an item.

It serves two purposes: it is the local preview's data, and it is the
reference for the csv columns.

```bash
python scripts/sample_data.py
cd site && python -m http.server 8000
```

That writes `site/manifest.json` and `site/sample-photos/` (both gitignored)
and serves the wall at `http://localhost:8000` — no `.env`, no AWS account and
no photos of your own. The password page and the upload form need the deployed
backend; the wall, the filters, the search and the lightbox all work.

## items.csv

| Column | Notes |
| --- | --- |
| `photos` | Comma-separated filenames, in order. The first is the cover |
| `id` | Optional. Blank means it is derived from the title. Once synced it is the item's permanent handle, so paste it back in if you want to retitle later |
| `title` | Shown on the card and in the lightbox |
| `caption` | Free text |
| `date` | `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. Drives sorting and the decade chips |
| `tags` | Space-separated, freeform. The filter chips are derived from what is used |

`Anorak's Almanac` has a blank `id` to show the derivation.

Replace them if you want a different demo — anything matching the layout
works.
