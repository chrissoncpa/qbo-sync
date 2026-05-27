/**
 * QBO Sync — workbook-bound Apps Script.
 *
 * Provides the user-facing menu and proxies clicks to the Cloud Run service.
 * The service URL is read from the _Config tab so it can be flipped without
 * redeploying the script.
 *
 * Milestones:
 *   - M1 (this file): menu skeleton, Cloud Run URL plumbing, getIdentityToken auth.
 *   - M4: "Refresh references now" calls the deployed /pull endpoint.
 *   - M5: "Push selected rows" / "Push all unposted" call /push.
 */

const CONFIG_TAB = "_Config";
const LOG_TAB = "_Log";
const SERVICE_URL_KEY = "CloudRunUrl";

/** Builds the QBO menu when the workbook opens. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("QBO")
    .addItem("Push selected rows", "menuPushSelected")
    .addItem("Push all unposted on this tab", "menuPushAllUnposted")
    .addSeparator()
    .addItem("Refresh references now", "menuRefreshReferences")
    .addSeparator()
    .addItem("Open run log", "menuOpenLog")
    .addItem("Open settings", "menuOpenConfig")
    .addToUi();
}

// ----- Menu actions ----------------------------------------------------------

function menuPushSelected() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const ranges = sheet.getActiveRangeList();
  if (!ranges) {
    toast_("Select at least one row first.");
    return;
  }
  const rowNumbers = collectRowNumbers_(ranges.getRanges());
  if (rowNumbers.length === 0) {
    toast_("No rows selected.");
    return;
  }
  callPush_(sheet.getName(), rowNumbers);
}

function menuPushAllUnposted() {
  const sheet = SpreadsheetApp.getActiveSheet();
  // The service decides which rows to push; sending no rowNumbers means "all unposted."
  callPush_(sheet.getName(), null);
}

function menuRefreshReferences() {
  const url = serviceUrl_();
  if (!url) {
    toast_("Set CloudRunUrl in _Config first.");
    return;
  }
  toast_("Refreshing references...");
  const resp = postJson_(`${url}/pull`, {});
  toast_(`Refresh: ${summarize_(resp)}`);
}

function menuOpenLog() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(LOG_TAB);
  if (sheet) sheet.activate();
  else toast_(`Sheet "${LOG_TAB}" not found.`);
}

function menuOpenConfig() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG_TAB);
  if (sheet) sheet.activate();
  else toast_(`Sheet "${CONFIG_TAB}" not found.`);
}

// ----- HTTP plumbing ---------------------------------------------------------

function callPush_(sheetName, rowNumbers) {
  const url = serviceUrl_();
  if (!url) {
    toast_("Set CloudRunUrl in _Config first.");
    return;
  }
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(2000)) {
    toast_("Another push is in progress. Try again in a moment.");
    return;
  }
  try {
    toast_(`Pushing ${rowNumbers ? rowNumbers.length + " row(s)" : "all unposted"}...`);
    const body = { sheet: sheetName };
    if (rowNumbers) body.rowNumbers = rowNumbers;
    const resp = postJson_(`${url}/push`, body);
    toast_(`Push: ${summarize_(resp)}`);
  } finally {
    lock.releaseLock();
  }
}

function postJson_(url, body) {
  const idToken = ScriptApp.getIdentityToken();
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: `Bearer ${idToken}` },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  };
  const resp = UrlFetchApp.fetch(url, options);
  const code = resp.getResponseCode();
  const text = resp.getContentText();
  if (code === 501) {
    return { error: "Service endpoint not yet implemented (milestone in progress)." };
  }
  if (code < 200 || code >= 300) {
    return { error: `HTTP ${code}: ${text.slice(0, 200)}` };
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    return { error: `Bad JSON response: ${text.slice(0, 200)}` };
  }
}

// ----- Helpers ---------------------------------------------------------------

function serviceUrl_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG_TAB);
  if (!sheet) return "";
  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === SERVICE_URL_KEY) return String(data[i][1] || "").trim();
  }
  return "";
}

function collectRowNumbers_(ranges) {
  const seen = {};
  const out = [];
  for (const r of ranges) {
    const start = r.getRow();
    const end = start + r.getNumRows() - 1;
    for (let row = start; row <= end; row++) {
      // Skip the header row (row 1).
      if (row > 1 && !seen[row]) {
        seen[row] = true;
        out.push(row);
      }
    }
  }
  return out;
}

function summarize_(resp) {
  if (!resp) return "no response";
  if (resp.error) return resp.error;
  const parts = [];
  if (resp.posted != null) parts.push(`${resp.posted} posted`);
  if (resp.errored != null) parts.push(`${resp.errored} errored`);
  if (resp.skipped != null) parts.push(`${resp.skipped} skipped`);
  return parts.length ? parts.join(", ") : JSON.stringify(resp);
}

function toast_(msg) {
  SpreadsheetApp.getActive().toast(msg, "QBO Sync", 5);
}
