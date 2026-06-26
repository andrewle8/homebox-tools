---
description: Add an Amazon product (or local folder) to Homebox inventory, end to end
argument-hint: <amazon-url | --folder PATH>
allowed-tools: Bash(python -m homebox_tools:*)
---

Add the product at `$ARGUMENTS` to Homebox. Drive the `homebox-tools` CLI — do not call the
Homebox or Amazon APIs directly.

Workflow:

1. **Preview first.** Run a dry run and read the JSON, never create blind:
   ```
   python -m homebox_tools "$ARGUMENTS" --dry-run --json
   ```
   (For a local folder use `python -m homebox_tools --folder PATH --dry-run --json`.)

2. **Summarize for the user.** Show cleaned name, price, manufacturer/model, manual count, and
   any `duplicate_warning`. If a duplicate is flagged, stop and ask whether to continue.

3. **Ask for the location.** Never auto-assign. Ask the user which Homebox location it goes in.
   Suggest tags from the categories already used in their inventory.

4. **Create it non-interactively.** Once you have a location, run the real command with `--yes`
   so manual uploads are auto-confirmed and nothing blocks on a prompt:
   ```
   python -m homebox_tools "$ARGUMENTS" --location "<LOCATION>" --tags <tag> <tag> --yes
   ```
   Use `--overrides '{"name":"..."}'` to fix a bad scraped name, or `--no-manuals` only if the
   user explicitly asks to skip manuals.

5. **Confirm.** Report the created item URL the CLI prints.

Error codes the CLI may return as JSON (`{"error": code, "message": ...}`): `cookie_expired`
(tell the user to run `python -m homebox_tools --login`), `captcha_detected`, `location_required`,
`location_not_found`, `config_not_found`, `scrape_error`. Surface the message; don't retry blindly.
