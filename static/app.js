/*
 * Dia de los Muertos Photo Booth — frontend controller (vanilla JavaScript, no frameworks).
 *
 * This script wires the upload form in templates/index.html to the backend
 * `POST /process` route. It uploads exactly one image as multipart form data,
 * shows a progress indicator while the request is in flight, reveals the
 * composited result as a blob image with a working download control, and
 * surfaces backend / network errors inline without ever reloading the page.
 *
 * Element contract (ids owned by the template):
 *   #upload-form        <form>  — intercepted on submit.
 *   #file-input         <input type="file"> — single JPEG/PNG (name="image").
 *   #submit-button      <button> — disabled while a request is in flight.
 *   #progress-indicator <div>   — shown during processing, hidden otherwise.
 *   #result-area        <section> — hidden until a result image exists.
 *   #result-image       <img>    — src set to the result blob object URL.
 *   #download-button    <a download> — enabled only when a result is available.
 *   #status-message     <div role="status"> — error / status text.
 *
 * Backend contract:
 *   POST /process, multipart field "image".
 *   Success: response.ok with an image/* Content-Type; body is the raw image
 *            bytes, with a Content-Disposition filename.
 *   Error:   JSON {"error": "<message>"} with status 400 (validation / no file
 *            / no face) or 503 (timeout).
 *
 * All code, comments, identifiers and user-facing strings are in English
 * (Req 10.7).
 */

(function () {
  "use strict";

  // --- Configuration -------------------------------------------------------

  // Endpoint and multipart field name expected by the Flask layer.
  var PROCESS_URL = "/process";
  var UPLOAD_FIELD_NAME = "image";

  // Utility class the CSS exposes alongside the `hidden` attribute. We toggle
  // the `hidden` attribute as the source of truth and keep the class in sync
  // so styling stays consistent with the template/CSS.
  var HIDDEN_CLASS = "is-hidden";

  // Fallback download filenames when the server does not provide a
  // Content-Disposition filename. The extension follows the response format so
  // the saved file keeps the same image format as the input (Req 7.3).
  var DEFAULT_DOWNLOAD_STEM = "dia-de-los-muertos-photo-booth";

  // User-facing messages owned by the frontend. Backend validation / no-face /
  // timeout messages arrive in the JSON body and are shown verbatim.
  var MESSAGES = {
    noFileSelected: "Please choose an image before creating your portrait.",
    networkError:
      "Something went wrong while reaching the spirits. Please try again.",
    unexpectedResponse:
      "The server returned an unexpected response. Please try again.",
    downloadFailed:
      "The download did not complete. The image is still available — try again.",
  };

  // --- Element references (resolved after the DOM is ready) ----------------

  var form;
  var fileInput;
  var submitButton;
  var progressIndicator;
  var resultArea;
  var resultImage;
  var downloadButton;
  var statusMessage;

  // Object URL currently backing the result image / download link. Tracked so
  // we can revoke it before creating a new one, avoiding memory leaks.
  var currentObjectUrl = null;

  // Guards against overlapping submissions while a request is in flight.
  var isProcessing = false;

  // --- Small DOM helpers ---------------------------------------------------

  /**
   * Hide an element using the `hidden` attribute (source of truth) and keep the
   * CSS utility class in sync.
   */
  function hideElement(element) {
    if (!element) {
      return;
    }
    element.hidden = true;
    element.classList.add(HIDDEN_CLASS);
  }

  /**
   * Show an element by clearing the `hidden` attribute and the utility class.
   */
  function showElement(element) {
    if (!element) {
      return;
    }
    element.hidden = false;
    element.classList.remove(HIDDEN_CLASS);
  }

  /**
   * Write a user-facing message into the status region. Passing an empty
   * string clears it.
   */
  function setStatusMessage(message) {
    if (statusMessage) {
      statusMessage.textContent = message || "";
    }
  }

  // --- Object URL lifecycle ------------------------------------------------

  /**
   * Revoke the current object URL (if any) so its memory can be reclaimed.
   * Safe to call repeatedly.
   */
  function revokeCurrentObjectUrl() {
    if (currentObjectUrl) {
      try {
        URL.revokeObjectURL(currentObjectUrl);
      } catch (error) {
        // Revoking is best-effort; never let cleanup throw.
      }
      currentObjectUrl = null;
    }
  }

  // --- Download control state ----------------------------------------------

  /**
   * Disable the download control. The link stays present but is inert: it is
   * marked aria-disabled, removed from the tab order, and its href points
   * nowhere actionable. Used on reset and whenever no result is available
   * (Req 7.2, 7.4).
   */
  function disableDownload() {
    if (!downloadButton) {
      return;
    }
    downloadButton.setAttribute("aria-disabled", "true");
    downloadButton.setAttribute("tabindex", "-1");
    downloadButton.setAttribute("href", "#");
    downloadButton.removeAttribute("download");
  }

  /**
   * Enable the download control for the given object URL and filename. The link
   * becomes focusable, its href points at the blob, and the `download`
   * attribute carries a non-empty filename so the browser saves rather than
   * navigates (Req 7.2, 7.4).
   */
  function enableDownload(objectUrl, filename) {
    if (!downloadButton) {
      return;
    }
    downloadButton.setAttribute("href", objectUrl);
    downloadButton.setAttribute("download", filename);
    downloadButton.setAttribute("tabindex", "0");
    downloadButton.setAttribute("aria-disabled", "false");
  }

  /**
   * True when a result is currently available for download.
   */
  function hasResult() {
    return (
      currentObjectUrl !== null &&
      downloadButton !== undefined &&
      downloadButton !== null &&
      downloadButton.getAttribute("aria-disabled") === "false"
    );
  }

  // --- Result area reset / display -----------------------------------------

  /**
   * Discard any partial or previous result: hide the result area, clear the
   * image source, disable the download, and revoke the backing object URL. Used
   * before a new submission and on errors so stale data never lingers
   * (Req 6.3).
   */
  function clearResult() {
    hideElement(resultArea);
    if (resultImage) {
      resultImage.removeAttribute("src");
    }
    disableDownload();
    revokeCurrentObjectUrl();
  }

  /**
   * Derive a non-empty download filename. Prefer the server's
   * Content-Disposition filename; otherwise fall back to a sensible default
   * whose extension matches the response content type (Req 7.3).
   */
  function resolveFilename(contentDisposition, contentType) {
    var fromHeader = parseContentDispositionFilename(contentDisposition);
    if (fromHeader) {
      return fromHeader;
    }
    var extension = "png";
    if (contentType && contentType.indexOf("image/jpeg") !== -1) {
      extension = "jpg";
    } else if (contentType && contentType.indexOf("image/png") !== -1) {
      extension = "png";
    }
    return DEFAULT_DOWNLOAD_STEM + "." + extension;
  }

  /**
   * Extract the filename from a Content-Disposition header value. Supports the
   * RFC 5987 `filename*=UTF-8''...` form and the plain `filename="..."` form.
   * Returns a non-empty string, or null when no usable filename is present.
   */
  function parseContentDispositionFilename(headerValue) {
    if (!headerValue) {
      return null;
    }

    // RFC 5987 extended form: filename*=UTF-8''encoded-name
    var extendedMatch = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(headerValue);
    if (extendedMatch && extendedMatch[1]) {
      var extended = extendedMatch[1].trim().replace(/^["']|["']$/g, "");
      try {
        extended = decodeURIComponent(extended);
      } catch (error) {
        // Fall through to the plain form if decoding fails.
      }
      if (extended) {
        return extended;
      }
    }

    // Plain form: filename="name" or filename=name
    var plainMatch = /filename\s*=\s*("?)([^";]+)\1/i.exec(headerValue);
    if (plainMatch && plainMatch[2]) {
      var plain = plainMatch[2].trim();
      if (plain) {
        return plain;
      }
    }

    return null;
  }

  /**
   * Show the composited result: set the image source to a freshly created
   * object URL, reveal the result area, and enable the download control. Any
   * previous object URL is revoked first to avoid leaks.
   */
  function displayResult(blob, contentDisposition) {
    // Revoke the previous URL before creating a new one (Req: avoid leaks).
    revokeCurrentObjectUrl();

    currentObjectUrl = URL.createObjectURL(blob);

    var filename = resolveFilename(contentDisposition, blob.type);

    if (resultImage) {
      resultImage.setAttribute("src", currentObjectUrl);
    }
    showElement(resultArea);
    enableDownload(currentObjectUrl, filename);
  }

  // --- Progress / submit button state --------------------------------------

  /**
   * Enter the "processing" state: show the progress indicator synchronously
   * (which satisfies the <=500 ms budget, Req 9.2) and disable the submit
   * button to prevent duplicate submissions.
   */
  function enterProcessingState() {
    isProcessing = true;
    showElement(progressIndicator);
    if (submitButton) {
      submitButton.disabled = true;
    }
  }

  /**
   * Leave the "processing" state: hide the progress indicator and re-enable the
   * submit button so the page is ready for another upload (Req 9.3).
   */
  function leaveProcessingState() {
    isProcessing = false;
    hideElement(progressIndicator);
    if (submitButton) {
      submitButton.disabled = false;
    }
  }

  // --- Response handling ---------------------------------------------------

  /**
   * Handle a successful (response.ok) image response: read it as a blob and
   * display it. If the content type is not an image, treat it as an unexpected
   * response.
   */
  function handleSuccessResponse(response) {
    var contentType = response.headers.get("Content-Type") || "";
    var contentDisposition = response.headers.get("Content-Disposition") || "";

    if (contentType.indexOf("image/") !== 0) {
      // Not the image payload we expected.
      clearResult();
      setStatusMessage(MESSAGES.unexpectedResponse);
      return;
    }

    return response.blob().then(function (blob) {
      displayResult(blob, contentDisposition);
      // Clear any lingering status text now that a result is shown.
      setStatusMessage("");
    });
  }

  /**
   * Handle an error response (400 / 503 / other non-ok). Parse the JSON
   * `{"error": ...}` body and show the message. Discard any previous result so
   * the page is ready for a brand-new upload without reloading (Req 6.3, 9.3).
   */
  function handleErrorResponse(response) {
    // A fresh error invalidates any previous result.
    clearResult();

    return response
      .json()
      .then(function (payload) {
        var message =
          payload && typeof payload.error === "string" && payload.error
            ? payload.error
            : MESSAGES.unexpectedResponse;
        setStatusMessage(message);
      })
      .catch(function () {
        // Body was not valid JSON — fall back to a generic message.
        setStatusMessage(MESSAGES.unexpectedResponse);
      });
  }

  // --- Submit flow ---------------------------------------------------------

  /**
   * Intercept the form submission: validate a file is present, then upload it
   * to the backend and route the response to the success / error handlers.
   */
  function handleSubmit(event) {
    event.preventDefault();

    // Ignore overlapping submissions while a request is in flight.
    if (isProcessing) {
      return;
    }

    // Validate that exactly one file has been selected (Req 1.1). With no file
    // we show a status message and do not submit.
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      clearResult();
      setStatusMessage(MESSAGES.noFileSelected);
      return;
    }

    var file = fileInput.files[0];

    // Starting a new request discards any previous/partial result (Req 6.3).
    clearResult();
    setStatusMessage("");

    var formData = new FormData();
    formData.append(UPLOAD_FIELD_NAME, file);

    // Show progress synchronously so it appears within the 500 ms budget and
    // stays visible until a result or error replaces it (Req 9.2).
    enterProcessingState();

    fetch(PROCESS_URL, {
      method: "POST",
      body: formData,
    })
      .then(function (response) {
        if (response.ok) {
          return handleSuccessResponse(response);
        }
        return handleErrorResponse(response);
      })
      .catch(function () {
        // Network / fetch-level failure: show a generic message and keep the
        // page usable. Any partial result has already been cleared above.
        clearResult();
        setStatusMessage(MESSAGES.networkError);
      })
      .then(function () {
        // Always leave the processing state so the indicator is hidden and the
        // submit button is usable again, regardless of outcome.
        leaveProcessingState();
      });
  }

  // --- Download flow -------------------------------------------------------

  /**
   * Guard the download activation. If no result is available the control is
   * inert and we do nothing (Req 7.2, 7.4). If delivering the file fails, show
   * an error while keeping the result displayed and the download available for
   * retry (Req 7.5).
   */
  function handleDownloadClick(event) {
    // When no result is available, the link must do nothing at all.
    if (!hasResult()) {
      event.preventDefault();
      return;
    }

    // A result is available: let the browser's native download proceed, but
    // wrap it so a delivery failure surfaces an error without tearing down the
    // result (Req 7.5).
    try {
      // Nothing extra to trigger here — the anchor's href + download attribute
      // drive the native download. This try/catch guards any environment where
      // attribute access or the navigation itself throws synchronously.
      if (!downloadButton.getAttribute("href") ||
          downloadButton.getAttribute("href") === "#") {
        throw new Error("Download target is not available.");
      }
    } catch (error) {
      event.preventDefault();
      // Keep the image displayed and the download enabled for a retry.
      setStatusMessage(MESSAGES.downloadFailed);
    }
  }

  // --- Initialization ------------------------------------------------------

  /**
   * Resolve element references and attach listeners. Called once the DOM is
   * ready (the template loads this script with `defer`).
   */
  function init() {
    form = document.getElementById("upload-form");
    fileInput = document.getElementById("file-input");
    submitButton = document.getElementById("submit-button");
    progressIndicator = document.getElementById("progress-indicator");
    resultArea = document.getElementById("result-area");
    resultImage = document.getElementById("result-image");
    downloadButton = document.getElementById("download-button");
    statusMessage = document.getElementById("status-message");

    // Start from a known clean state: no result, progress hidden.
    hideElement(progressIndicator);
    clearResult();
    setStatusMessage("");

    if (form) {
      form.addEventListener("submit", handleSubmit);
    }
    if (downloadButton) {
      downloadButton.addEventListener("click", handleDownloadClick);
    }
    if (fileInput) {
      // Selecting a new file clears any stale error so the page feels ready.
      fileInput.addEventListener("change", function () {
        setStatusMessage("");
      });
    }
  }

  // The template uses `defer`, so the DOM is parsed by the time this runs.
  // Guard anyway in case the script is ever loaded without `defer`.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
