/**
 * AI Verdant — Google Apps Script (optional add-on)
 * ------------------------------------------------------------------
 * The Python backend already writes rows into the "Readings" sheet
 * directly via the Sheets API (see backend/sheets_integration.py).
 * This script is optional and adds two conveniences INSIDE the sheet:
 *
 *   1. onEdit-safe conditional formatting refresh for out-of-range cells
 *   2. A custom menu item "AI Verdant > Email me a daily summary"
 *
 * Install:
 *   Open your Google Sheet -> Extensions -> Apps Script -> paste this file
 *   -> Save -> Run `onOpen` once to authorize.
 */

const SHEET_NAME = "Readings";
const IDEAL_RANGES = {
  "Temperature (°C)": [18, 30],
  "Humidity (%)": [40, 70],
  "Soil Moisture (%)": [35, 65],
  "pH": [6.0, 7.0],
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("AI Verdant")
    .addItem("Highlight out-of-range readings", "highlightOutOfRange")
    .addItem("Email me a daily summary", "emailDailySummary")
    .addToUi();
}

function highlightOutOfRange() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  if (!sheet) return;
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  Object.keys(IDEAL_RANGES).forEach((colName) => {
    const colIndex = headers.indexOf(colName) + 1;
    if (colIndex === 0) return;
    const range = sheet.getRange(2, colIndex, lastRow - 1, 1);
    const values = range.getValues();
    const [low, high] = IDEAL_RANGES[colName];
    const backgrounds = values.map(([v]) => {
      if (v === "" || v === null) return ["#ffffff"];
      return (v < low || v > high) ? ["#ffe3f8"] : ["#e3ffef"];
    });
    range.setBackgrounds(backgrounds);
  });
}

function emailDailySummary() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  if (!sheet) return;
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const lastReading = sheet.getRange(lastRow, 1, 1, sheet.getLastColumn()).getValues()[0];

  let body = "Latest AI Verdant reading:\n\n";
  headers.forEach((h, i) => { body += `${h}: ${lastReading[i]}\n`; });

  const email = Session.getActiveUser().getEmail();
  if (email) {
    MailApp.sendEmail(email, "AI Verdant — Daily Farm Summary", body);
  }
}
