# infrastructure/

Terraform for the whole stack, and the source of both Lambdas.

`aws_region` defaults to `ap-southeast-2`. The region must support Lambda
function URLs. `ap-southeast-6` does not.

There is no `terraform.tfvars`, and `tf.py` will not run while one exists.
Set values in `.env`, or change a default in `variables.tf`.

`tf.py` builds any missing Lambda bundle before calling terraform.

Run Terraform through [`scripts/tf.py`](../scripts/README.md), which loads
`.env` and adds `-chdir` for this directory. A bare `terraform apply` here
stops and asks for the four variables that have no default.

## What gets created

| File | Resources |
| --- | --- |
| `s3.tf` | The bucket, its public-access block, versioning, the CloudFront origin access control, the bucket policy and the CORS rule for browser uploads |
| `cloudfront.tf` | One distribution, four origins and the cache behaviours below |
| `acm.tf` | The certificate, validated by DNS records you add yourself |
| `secrets.tf` | The cookie-signing key pair, the CloudFront key group, and three SSM SecureStrings: the private key, the site password and the session secret |
| `lambda.tf` | IAM roles and policies, both functions, and their function URLs |
| `variables.tf` | Inputs. The four deployment-specific ones have no default; region, resource-name prefix and session length default here |

## Request routing

```
browser ── CloudFront ─┬─ /login.html, /style.css   public
                       ├─ everything else           signed cookies → S3 site/
                       ├─ /images/*, /data/*        signed cookies → S3
                       ├─ /auth/*                   gate Lambda
                       └─ /api/*                    items-api Lambda
```

Every behaviour except the two public assets carries a trusted key group, so a
viewer without valid signed cookies gets a 403. A `custom_error_response` maps
that 403 to `/login.html` with a 200.

Both function URLs are `authorization_type = "NONE"` and are protected by an
`X-Origin-Verify` header that CloudFront adds and each function checks, so the
URLs are not usable directly.

## The Lambdas

`lambda/gate/` — `POST /auth/login` compares the submitted password against
the SSM SecureString, then issues three CloudFront signed cookies scoped to
the whole site plus an `mm_session` HMAC cookie scoped to `/api/*`.
`GET /auth/logout` expires all four. A wrong password costs one second.

`lambda/items-api/` — `POST /api/upload-url` returns presigned S3 PUT URLs,
`POST /api/items` writes a record, `PATCH /api/items/{id}` edits one,
`DELETE /api/items/{id}` removes one, and each write rebuilds
`data/manifest.json`. Every route re-verifies the `mm_session` HMAC. Record
writes are conditional PutObjects (`If-Match`, or `If-None-Match: *` on a
first write).

Both handlers take their configuration from Lambda environment variables set
in `lambda.tf`. Neither contains a domain, bucket or account id.

Bundles are assembled by `python scripts/build_lambdas.py` into
`infrastructure/build/<name>/` and zipped from there by `archive_file`. Run it
before the first apply and after any handler or `requirements.txt` change.

## Variables

| Variable | Default | From |
| --- | --- | --- |
| `bucket_name` | none | `.env` `S3_BUCKET` |
| `domain_name` | none | `.env` `DOMAIN_NAME` |
| `aws_profile` | none | `.env` `AWS_PROFILE` |
| `site_password` | none | `.env` `SITE_PASSWORD` |
| `aws_region` | `ap-southeast-2` | `variables.tf`, or `.env` `AWS_REGION` |
| `project_name` | `mementos` | `variables.tf`, or `.env` `PROJECT_NAME` |
| `session_hours` | `720` | `variables.tf`, or `.env` `SESSION_HOURS` |

## Applying

The certificate has to validate before the distribution can use it, so the
first deploy is two applies with a DNS change in between.

```bash
python scripts/tf.py cert             # applies the certificate and prints its record
# add the CNAMEs from the acm_validation_records output at your registrar
python scripts/tf.py apply            # completes
# point your domain at the cloudfront_domain_name output
```

Changing the password is `SITE_PASSWORD` in `.env` and another apply. The
Lambda reads SSM at call time, so no rebuild is needed.

## Outputs

`site_domain`, `cloudfront_distribution_id`, `cloudfront_domain_name`,
`acm_validation_records`, `bucket_name`. `scripts/deploy_site.py` reads the
first two.

State holds the password, the private key and every resource id. Keep it out
of the repository — `*.tfstate` is gitignored.
