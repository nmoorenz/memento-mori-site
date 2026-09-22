# Mementos

A private wall of keepsakes — badges, certificates, tickets, t-shirts, the
things that are hard to throw out. Photograph the object, say what it is, and
it joins the wall.

One shared password, no user accounts, no comments. Runs on AWS: S3,
CloudFront and two Python Lambdas.

## Layout

| Folder | What's in it |
| --- | --- |
| [`infrastructure/`](infrastructure/README.md) | Terraform for S3, CloudFront, ACM, the cookie-signing keys and both Lambdas, plus the Lambda source |
| [`scripts/`](scripts/README.md) | The Terraform wrapper, the bulk-load CLI, the Lambda bundler, the deploy script and the sample-data generator |
| [`site/`](site/README.md) | The frontend: the wall, the lightbox, the upload form and the password page |
| [`example/`](example/README.md) | Invented items and placeholder photos: the local preview's data |
| [`photos/`](photos/README.md) | Your own `items.csv` and photos. Gitignored |

## Getting started

Needs Python 3.12+, Terraform and the AWS CLI. To see the site without an AWS
account or any setup:

```bash
pip install -r requirements.txt
python scripts/sample_data.py
cd site && python -m http.server 8000
```

That builds the wall from `example/` and serves it at
`http://localhost:8000`. The password page and the upload form need the
deployed backend.

To deploy:

```bash
cp env.example .env          # fill in bucket, domain, profile, password
cp example/items.csv photos/items.csv
python scripts/build_lambdas.py
python scripts/tf.py init
python scripts/tf.py cert    # applies the certificate and prints its record
# add the CNAMEs from the acm_validation_records output at your registrar
python scripts/tf.py apply
# point your domain's DNS at the cloudfront_domain_name output
python scripts/deploy_site.py
```

Every Terraform command goes through `scripts/tf.py`, which loads `.env` and
passes the values in as `TF_VAR_*`. See
[`scripts/README.md`](scripts/README.md) for the full `.env` reference.

## Privacy

This repository is a public record of the work. It contains no deployment.

**Not in the repository**, and gitignored:

- `.env` — domain, bucket, AWS profile, site password
- `photos/` — photographs of real objects and the `items.csv` describing them
- `build/` — what a deploy generates, including a `config.js` carrying the
  real site name
- Terraform state, which holds resource ids and the password

**In the repository**, deliberately: `example/` with invented items and
generated placeholder images, and `env.example` with placeholders. There is
no `terraform.tfvars`: the non-identifying defaults live in `variables.tf`.

No Terraform variable that is globally unique or identifying has a default, so
an incomplete `.env` fails before anything is created.

Docs use `example.com` and `your-bucket-name` throughout. If you fork this,
the same boundaries apply to you: put your values in `.env`, leave them out of
everything else.

## Licence

None yet — add one before relying on this.
