# Apps Script — workbook-bound

This folder is a [clasp](https://github.com/google/clasp)-managed Apps Script project that lives inside the QBO Sync workbook.

## Setup

1. Install clasp: `npm install -g @google/clasp`.
2. Log in: `clasp login`.
3. Create the script bound to the workbook:
   ```bash
   clasp create --type sheets --rootDir . --title "QBO Sync"
   ```
   (Or, if you've already created a script, link this folder with `clasp clone <scriptId>`.)
4. Push the code: `clasp push -f`.
5. Open the workbook in Sheets, refresh, and the **QBO** menu should appear.
6. The first menu click triggers an authorization dialog — grant the requested scopes.

## What's wired up at M1

- `onOpen` builds the **QBO** menu.
- Menu items prompt and toast meaningful messages, but the underlying HTTP calls return `501` until the corresponding service milestones are deployed.
- The Cloud Run URL is read from the workbook's `_Config` tab (`CloudRunUrl` key). Once you deploy the service, paste the URL into that cell — no script edit needed.

## Scopes

See `appsscript.json`. We use the narrow `spreadsheets.currentonly` scope so the script can only read/write the workbook it's bound to, not the user's other sheets.
