// Photo upload: pick or take a photo, shrink it in the browser (longest side 1600 px,
// JPEG), then send it. Markup: <input type="file" accept="image/*"
// data-photo-upload="/cars/<id>/photo">
(function () {
  var MAX_SIDE = 1600;

  function toJpeg(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) {
          blob ? resolve(blob) : reject(new Error("The photo couldn't be resized."));
        }, "image/jpeg", 0.85);
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("The photo couldn't be read."));
      };
      img.src = url;
    });
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[data-photo-upload]") || !input.files.length) return;
    var status = document.getElementById(input.dataset.status || "photo-status");
    function say(text) {
      if (status) status.textContent = text;
    }
    say("Uploading…");
    toJpeg(input.files[0])
      .then(function (blob) {
        var body = new FormData();
        body.append("photo", blob, "photo.jpg");
        return fetch(input.dataset.photoUpload, { method: "POST", body: body, credentials: "same-origin" });
      })
      .then(function (response) {
        if (response.ok) return window.location.reload();
        return response.json().then(
          function (body) {
            throw new Error(typeof body.detail === "string" ? body.detail : "");
          },
          function () {
            throw new Error("");
          }
        );
      })
      .catch(function (error) {
        say(error.message || "The photo couldn't be uploaded. Try again.");
        input.value = "";
      });
  });

  // Invoice upload: send the PDF with fetch (a form navigation can lose the file on
  // iPhone Safari) and follow the {"next": url} the server answers with.
  window.uploadInvoice = true;
  document.addEventListener("change", function (event) {
    var input = event.target;
    var form = input.form;
    if (!form || !form.matches("form[data-invoice-upload]") || input.type !== "file" || !input.files.length) return;
    var status = document.getElementById("invoice-status");
    function say(text, isError) {
      if (!status) return;
      status.textContent = text;
      status.classList.toggle("text-red-600", !!isError);
      status.classList.toggle("dark:text-red-400", !!isError);
    }
    input.disabled = true;
    say("Uploading…");
    var body = new FormData();
    body.append("car_id", form.elements.car_id.value);
    body.append("invoice", input.files[0], input.files[0].name);
    fetch(form.action, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response.json().then(
          function (data) {
            if (response.ok && typeof data.next === "string") return (window.location.href = data.next);
            throw new Error(typeof data.detail === "string" ? data.detail : "");
          },
          function () {
            throw new Error("");
          }
        );
      })
      .catch(function (error) {
        say(error.message || "The invoice couldn't be uploaded. Try again.", true);
        input.value = "";
        input.disabled = false;
      });
  });
})();
