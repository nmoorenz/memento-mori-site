// Placeholders for local preview only. This committed copy is never given
// real values: scripts/deploy_site.sh writes the deployed one into
// build/site/config.js and uploads that, so nothing deployment-specific
// appears in the working tree.
//
// `python scripts/sample_data.py` generates ./manifest.json and
// ./sample-photos/ next to this file, which is what MANIFEST_URL points at.
export const MANIFEST_URL = "./manifest.json";
export const API_BASE = "/api";
export const SITE_TITLE = "Mementos";
