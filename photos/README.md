# photos/

Your own data: `items.csv` and the photos, flat in this folder. Everything
here except this file and `.gitkeep` is gitignored, so nothing reaches a
public repository.

Your filenames are never changed. Drop the photos in as they came off the
camera or scanner, and list them in the csv's `photos` column:

```
photos/
    items.csv
    IMG_4821.JPG
    IMG_4822.JPG
    scan_0007.jpg
```

```csv
photos,id,title,caption,date,tags
"IMG_4821.JPG, IMG_4822.JPG",copper-key,Copper Key,"First of the three.",2045,keys quest
scan_0007.jpg,,Anorak's Almanac,"Read until the pages fell apart.",2040,books
```

Leave `id` blank and it is derived from the title. After an item is synced its
id is its permanent handle, so paste the derived one back into the csv if you
later want to change the title without orphaning the item.

The first filename listed is the cover; the rest follow in that order.
Separate them with commas (so a name may contain spaces); a cell with no
comma is split on whitespace instead. Matching ignores case, since a csv
written by hand rarely agrees with what a camera capitalised.

`check` reports both directions — a listed file that isn't there, and a file
here that no row claims — so a typo surfaces instead of quietly going
missing.

```bash
python scripts/item_sync.py check              # no AWS, just reports
python scripts/sample_data.py --source photos  # preview before uploading
python scripts/item_sync.py sync               # upload and rebuild
```

Originals are uploaded under their own names, so
`python scripts/item_sync.py download --yes` brings them back here matching
what `items.csv` already lists.

[`example/`](../example/README.md) has the same layout with invented items and
placeholder photos.
