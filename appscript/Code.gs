/**
 * QBO Sync — workbook-bound Apps Script.
 *
 * SETUP (one-time):
 *   1. In the spreadsheet: Extensions → Apps Script
 *   2. Project Settings → Script Properties → Add properties:
 *        SERVICE_URL  = https://YOUR_CLOUD_RUN_URL
 *        COMPANY_API_KEY = <key issued by POST /companies>   (multi-tenant only)
 *   3. Save and close Apps Script editor.
 *   4. Reload the spreadsheet — the QBO menu will appear.
 *   5. First use: approve the permission dialog (external requests + identity).
 */

var TRANSACTION_TABS = [
  "Bills",
  "Invoices",
  "Expenses",
  "Sales Receipts",
  "Deposits",
  "Journal Entries",
];

// ─── Menu ────────────────────────────────────────────────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("QBO")
    .addItem("Push selected rows",    "menuPushSelected")
    .addItem("Push all pending rows", "menuPushAllPending")
    .addSeparator()
    .addItem("Pull reference data",   "menuPullReferenceData")
    .addSeparator()
    .addItem("Open run log",          "menuOpenLog")
    .addToUi();
}

// ─── Menu actions ─────────────────────────────────────────────────────────────

function menuPushSelected() {
  var url = serviceUrl_();
  if (!url) return;

  var sheet   = SpreadsheetApp.getActiveSheet();
  var tabName = sheet.getName();

  if (TRANSACTION_TABS.indexOf(tabName) === -1) {
    toast_(
      '"' + tabName + '" is not a transaction tab.\n' +
      "Select rows in: " + TRANSACTION_TABS.join(", ")
    );
    return;
  }

  var rangeList = sheet.getActiveRangeList();
  if (!rangeList) {
    toast_("Select at least one data row first.");
    return;
  }

  var rowNumbers = collectRowNumbers_(rangeList.getRanges());
  if (rowNumbers.length === 0) {
    toast_("No data rows selected — row 1 is the header.");
    return;
  }

  var lock = LockService.getDocumentLock();
  if (!lock.tryLock(3000)) {
    toast_("Another push is in progress — try again in a moment.");
    return;
  }
  try {
    toast_("Pushing " + rowNumbers.length + " row(s) from " + tabName + " …");
    var body = { selection: [{ tab: tabName, rows: rowNumbers }] };
    var resp = postJson_(url + "/push", body);
    toast_(pushSummary_(resp));
  } finally {
    lock.releaseLock();
  }
}

function menuPushAllPending() {
  var url = serviceUrl_();
  if (!url) return;

  var lock = LockService.getDocumentLock();
  if (!lock.tryLock(3000)) {
    toast_("Another push is in progress — try again in a moment.");
    return;
  }
  try {
    toast_("Pushing all pending rows across all tabs …");
    var resp = postJson_(url + "/push", {});
    toast_(pushSummary_(resp));
  } finally {
    lock.releaseLock();
  }
}

function menuPullReferenceData() {
  var url = serviceUrl_();
  if (!url) return;

  toast_("Pulling reference data from QBO …");
  var resp = postJson_(url + "/pull", {});
  if (resp.error) {
    toast_("Pull failed: " + resp.error);
    return;
  }
  var tabs = resp.tabs || {};
  var lines = Object.keys(tabs).map(function (k) { return k + ": " + tabs[k]; });
  toast_("Pull complete — " + (lines.length ? lines.join(", ") : "no tabs updated"));
}

function menuOpenLog() {
  var sheet = SpreadsheetApp.getActive().getSheetByName("_Log");
  if (sheet) {
    sheet.activate();
  } else {
    toast_('Sheet "_Log" not found.');
  }
}

// ─── HTTP plumbing ────────────────────────────────────────────────────────────

function postJson_(url, body) {
  var token  = ScriptApp.getIdentityToken();
  var apiKey = (PropertiesService.getScriptProperties().getProperty("COMPANY_API_KEY") || "").trim();
  var headers = { Authorization: "Bearer " + token };
  if (apiKey) {
    headers["X-Api-Key"] = apiKey;
  }
  var options = {
    method:      "post",
    contentType: "application/json",
    headers:     headers,
    payload:     JSON.stringify(body),
    muteHttpExceptions: true,
  };

  var response;
  try {
    response = UrlFetchApp.fetch(url, options);
  } catch (e) {
    return { error: "Network error: " + e.message };
  }

  var code = response.getResponseCode();
  var text = response.getContentText();

  if (code < 200 || code >= 300) {
    return { error: "HTTP " + code + ": " + text.slice(0, 200) };
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    return { error: "Unexpected response: " + text.slice(0, 200) };
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function serviceUrl_() {
  var url = (PropertiesService.getScriptProperties().getProperty("SERVICE_URL") || "").trim();
  if (!url) {
    SpreadsheetApp.getUi().alert(
      "SERVICE_URL is not configured.\n\n" +
      "Go to Extensions → Apps Script → Project Settings → Script Properties\n" +
      "and add:\n  SERVICE_URL = https://YOUR_CLOUD_RUN_URL"
    );
    return null;
  }
  return url.replace(/\/$/, "");
}

function collectRowNumbers_(ranges) {
  var seen = {};
  var out  = [];
  for (var i = 0; i < ranges.length; i++) {
    var start = ranges[i].getRow();
    var end   = start + ranges[i].getNumRows() - 1;
    for (var row = start; row <= end; row++) {
      if (row > 1 && !seen[row]) {   // skip header (row 1)
        seen[row] = true;
        out.push(row);
      }
    }
  }
  return out;
}

function pushSummary_(resp) {
  if (!resp)       return "No response from server.";
  if (resp.error)  return "Error: " + resp.error;
  var parts = [];
  if (resp.posted  != null) parts.push(resp.posted  + " posted");
  if (resp.errored != null) parts.push(resp.errored + " errored");
  if (resp.skipped != null) parts.push(resp.skipped + " skipped");
  return parts.length ? parts.join(", ") : JSON.stringify(resp);
}

function toast_(msg) {
  SpreadsheetApp.getActive().toast(msg, "QBO Sync", 7);
}
