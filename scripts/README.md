# scripts/

Everything here reads the same `.env` at the repository root. Copy
`env.example` to `.env` and fill it in first.

| Script | What it does |
| --- | --- |
| `tf.py` | Runs Terraform with `.env` mapped to `TF_VAR_*` |
| `build_lambdas.py` | Assembles the Lambda bundles Terraform zips |
| `deploy_site.py` | Pushes `site/` to S3 with a generated config.js |
| `item_sync.py` | Bulk-loads photos and maintains the deployed items |
| `sample_data.py` | Builds the local preview from `example/`. Needs no `.env` |

## `.env`

| Variable | Required | What it is |
| --- | --- | --- |
| `S3_BUCKET` | yes | Bucket to create. Globally unique across all of AWS |
| `DOMAIN_NAME` | yes | Domain the site is served on, e.g. `mementos.example.com` |
| `AWS_PROFILE` | yes | AWS CLI profile to deploy with |
| `SITE_PASSWORD` | yes | The shared password for the gate |
| `SITE_TITLE` | no | Name in the header and the browser tab. Default `Mementos` |
| `AWS_REGION` | no | Overrides the default in `variables.tf`. Default `ap-southeast-2` |
| `PROJECT_NAME` | no | Prefix for AWS resource names. Default `mementos` |
| `SESSION_HOURS` | no | How long a login lasts. Default `720` |

`.env` is gitignored. Nothing else in the repository holds these values.

## `tf.py`

```bash
python scripts/tf.py init
python scripts/tf.py cert                            # first-stage certificate apply
python scripts/tf.py apply
python scripts/tf.py output -raw cloudfront_domain_name
```

`cert` is the only argument tf.py handles itself: it applies the certificate
alone and prints its DNS validation record. Everything else goes through to
terraform untouched.

Loads `.env` with `python-dotenv`, exports each value as its `TF_VAR_*`, adds
`-chdir=infrastructure`, and passes every other argument through to
`terraform`. A missing required value stops with a message naming it. Use this
rather than calling `terraform` directly — the four required variables have no
defaults. Set `TERRAFORM` to use a terraform binary that is not on PATH.

`tf.py` will not run while `infrastructure/terraform.tfvars` or any
`*.auto.tfvars` exists — terraform loads those automatically and they override
the values passed from `.env`, silently. It builds any missing
`infrastructure/build/<name>/` bundle before calling terraform.

## `build_lambdas.py`

```bash
python scripts/build_lambdas.py
```

For each directory under `infrastructure/lambda/`, copies the handler and
installs its `requirements.txt` into `infrastructure/build/<name>/`.
Dependencies are installed for Lambda's platform (`manylinux2014_x86_64`,
cp312), so building on any OS produces a bundle that runs on Lambda. Run
before the first apply and after any handler change.

## `deploy_site.py`

```bash
python scripts/deploy_site.py
```

Syncs `site/` to `s3://$S3_BUCKET/site/` and invalidates the distribution. It
writes `build/config.js` with `SITE_TITLE` from `.env` and the deployed paths
and uploads it from there; the committed `site/config.js` keeps its
placeholders. Run it after an apply, or after any frontend change.

Reads `site_domain` and `cloudfront_distribution_id` through `tf.py`. Needs
`.env`, terraform and the aws CLI on PATH.

## `item_sync.py`

Bulk-loads from `photos/`, driven by `photos/items.csv`. Photos keep their own
filenames; the csv's `photos` column maps them to items. See
[`photos/README.md`](../photos/README.md) for the layout and
[`example/README.md`](../example/README.md) for the columns.

```bash
python scripts/item_sync.py check          # match the csv to the files, no AWS
python scripts/item_sync.py sync           # upload, write records, rebuild
python scripts/item_sync.py sync --prune   # also drop images gone locally
python scripts/item_sync.py export         # records back out to csv
python scripts/item_sync.py rename --item old-id --to new-id
python scripts/item_sync.py delete --item some-id --photos --yes
python scripts/item_sync.py download --yes # originals back into ./photos
```

The source of truth is `data/items/<id>.json` in S3, one record per item.
`data/manifest.json` is derived and rebuilt from the records by both this
script and items-api. `sync` writes csv rows into records and never deletes a
record that has no row, so items added through the site's own form survive.

The filename convention lives in `parse_photo_name()` and nowhere else.
`rename` moves a record and its images together.

## `sample_data.py`

```bash
python scripts/sample_data.py                  # from example/
python scripts/sample_data.py --source photos  # from your own, pre-upload
cd site && python -m http.server 8000
```

Reads `items.csv` and the photos its `photos` column lists, builds thumb and
full derivatives with the same code a real sync uses, and writes
`site/manifest.json` and `site/sample-photos/`. Both are gitignored. Needs no
`.env` and no credentials.
