// PurifyDocs frontend application logic.
(function () {
  "use strict";

  var API = window.PURIFYDOCS_CONFIG.API_BASE_URL.replace(/\/$/, "");

  // ---- Drop zone & file upload ----

  var dropZone = document.getElementById("dropZone");
  var fileInput = document.getElementById("fileInput");
  var loadingEl = document.getElementById("scanLoading");
  var errorEl = document.getElementById("scanError");
  var resultsEl = document.getElementById("scanResults");

  dropZone.addEventListener("click", function () {
    fileInput.click();
  });

  dropZone.addEventListener("dragover", function (e) {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", function () {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files.length > 0) {
      handleFile(fileInput.files[0]);
    }
  });

  function handleFile(file) {
    showLoading(true);
    hideError();
    hideResults();

    var formData = new FormData();
    formData.append("file", file);

    fetch(API + "/scan/full", {
      method: "POST",
      body: formData,
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (err) {
            throw new Error(err.detail || "Scan failed (HTTP " + resp.status + ")");
          });
        }
        return resp.json();
      })
      .then(function (data) {
        showLoading(false);
        renderResults(file.name, data);
      })
      .catch(function (err) {
        showLoading(false);
        showError(err.message);
      });
  }

  // ---- State helpers ----

  function showLoading(show) {
    if (show) loadingEl.classList.remove("hidden");
    else loadingEl.classList.add("hidden");
  }

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  }

  function hideError() {
    errorEl.classList.add("hidden");
  }

  function hideResults() {
    resultsEl.classList.add("hidden");
  }

  // ---- Result rendering ----

  function renderResults(filename, data) {
    var report = data.report || {};
    var safe = data.safe_payload || {};
    var safeText = data.safe_text || "";
    var issues = report.issues || [];
    var isClean = report.is_clean;

    var html = "";

    // Summary bar
    html += '<div class="result-summary">';
    html += '  <div class="result-filename">' + esc(filename) + "</div>";
    html += '  <div class="result-metrics">';
    html += '    <span class="metric"><label>Issues</label><span class="value ' + (isClean ? "value-ok" : "value-warn") + '">' + issues.length + "</span></span>";
    html += '    <span class="metric"><label>Type</label><span class="value">' + esc((report.file_type || "").split("/").pop()) + "</span></span>";
    html += '    <span class="metric"><label>Size</label><span class="value">' + formatBytes(report.size_bytes || 0) + "</span></span>";
    html += '    <span class="metric"><label>Time</label><span class="value">' + Math.round(report.processing_time_ms || 0) + " ms</span></span>";
    html += "  </div>";
    html += "</div>";

    // Status banner
    if (isClean) {
      html += '<div class="banner banner-ok">No issues detected — document appears clean.</div>';
    } else {
      html += '<div class="banner banner-warn">' + issues.length + " issue(s) detected.</div>";
    }

    // SHA-256
    html += '<div class="sha-box"><strong>SHA-256:</strong> <code>' + esc(report.sha256 || "") + "</code></div>";

    // Download buttons
    var stem = filename.replace(/\.[^.]+$/, "");
    html += '<div class="download-row">';
    html += '  <button class="btn btn-small" onclick="downloadJSON(' + JSON.stringify(JSON.stringify(report)) + ', \'' + esc(stem) + '_report.json\')">Report (.json)</button>';
    html += '  <button class="btn btn-small" onclick="downloadText(' + JSON.stringify(JSON.stringify(safeText)) + ', \'' + esc(stem) + '_safe_text.txt\')">Safe Text (.txt)</button>';
    html += '  <button class="btn btn-small" onclick="downloadJSON(' + JSON.stringify(JSON.stringify(safe)) + ', \'' + esc(stem) + '_safe_payload.json\')">Safe Payload (.json)</button>';
    html += "</div>";

    // Issues list
    if (issues.length > 0) {
      html += '<h3>Detected Issues</h3>';
      issues.forEach(function (issue, i) {
        var icon = issue.severity === "high" ? "🔴" : issue.severity === "medium" ? "🟡" : "🟢";
        html += '<details class="issue-item">';
        html += '  <summary>' + icon + " " + esc(issue.code) + " — " + esc(issue.message) + "</summary>";
        html += '  <div class="issue-detail">';
        html += "    <p><strong>Severity:</strong> " + esc(issue.severity) + "</p>";
        html += "    <p><strong>Code:</strong> <code>" + esc(issue.code) + "</code></p>";
        if (issue.location && Object.keys(issue.location).length > 0) {
          html += "    <p><strong>Location:</strong> " + esc(JSON.stringify(issue.location)) + "</p>";
        }
        html += "    <p><strong>Evidence:</strong></p>";
        html += '    <pre class="evidence">' + esc((issue.evidence || "").slice(0, 500)) + "</pre>";
        html += "  </div>";
        html += "</details>";
      });
    }

    // Visible vs extracted text
    html += '<h3>Human-Visible vs Machine-Extracted Text</h3>';
    html += '<div class="text-compare">';
    html += '  <div class="text-col">';
    html += "    <h4>Visible Text</h4>";
    html += '    <div class="text-box">' + esc(report.visible_text || "(empty)") + "</div>";
    html += "  </div>";
    html += '  <div class="text-col">';
    html += "    <h4>Extracted Text</h4>";
    html += '    <div class="text-box">' + highlightHidden(report.visible_text || "", report.extracted_text || "") + "</div>";
    html += "  </div>";
    html += "</div>";

    if ((report.extracted_text || "").length > (report.visible_text || "").length) {
      var delta = (report.extracted_text || "").length - (report.visible_text || "").length;
      html += '<div class="info-box">Extracted text is ' + delta + " characters longer than visible text — hidden content may be present.</div>";
    }

    // Safe text
    html += '<h3>Sanitized Safe Text</h3>';
    html += '<textarea class="safe-text-area" readonly>' + esc((safeText || "").slice(0, 8000)) + "</textarea>";

    // Metadata
    if (report.metadata && Object.keys(report.metadata).length > 0) {
      html += '<h3>Metadata</h3>';
      html += '<pre class="metadata-box">' + esc(JSON.stringify(report.metadata, null, 2)) + "</pre>";
    }

    resultsEl.innerHTML = html;
    resultsEl.classList.remove("hidden");
  }

  // ---- Helpers ----

  function esc(s) {
    var div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  function formatBytes(n) {
    var units = ["B", "KB", "MB", "GB"];
    for (var i = 0; i < units.length; i++) {
      if (n < 1024) return n.toFixed(1) + " " + units[i];
      n /= 1024;
    }
    return n.toFixed(1) + " TB";
  }

  function highlightHidden(visible, extracted) {
    var visibleLines = (visible || "").split("\n");
    var visibleSet = {};
    visibleLines.forEach(function (l) {
      var t = l.trim();
      if (t) visibleSet[t] = true;
    });
    var extractedLines = (extracted || "").split("\n");
    var out = extractedLines.map(function (line) {
      var t = line.trim();
      if (t && !visibleSet[t]) {
        return '<span class="hidden-line">' + esc(line) + "</span>";
      }
      return esc(line);
    });
    return out.join("\n");
  }

  window.downloadJSON = function (str, filename) {
    download(str, filename, "application/json");
  };

  window.downloadText = function (str, filename) {
    download(str, filename, "text/plain");
  };

  function download(str, filename, mime) {
    var blob = new Blob([str], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ---- Detector tabs ----

  var tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      tabBtns.forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });
})();
