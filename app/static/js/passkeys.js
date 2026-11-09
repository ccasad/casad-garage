// Passkey setup and sign-in (WebAuthn). Buttons opt in with data-passkey="register|login".
// Uses event delegation so it keeps working after hx-boost swaps the page body.
(function () {
  function toBytes(value) {
    var base64 = value.replace(/-/g, "+").replace(/_/g, "/");
    var binary = atob(base64 + "===".slice((base64.length + 3) % 4));
    return Uint8Array.from(binary, function (c) { return c.charCodeAt(0); });
  }

  function toBase64url(buffer) {
    var binary = String.fromCharCode.apply(null, new Uint8Array(buffer));
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function descriptors(list) {
    return (list || []).map(function (c) { return Object.assign({}, c, { id: toBytes(c.id) }); });
  }

  function serialize(credential) {
    var r = credential.response;
    var response = { clientDataJSON: toBase64url(r.clientDataJSON) };
    if (r.attestationObject) {
      response.attestationObject = toBase64url(r.attestationObject);
      response.transports = r.getTransports ? r.getTransports() : [];
    } else {
      response.authenticatorData = toBase64url(r.authenticatorData);
      response.signature = toBase64url(r.signature);
      response.userHandle = r.userHandle ? toBase64url(r.userHandle) : null;
    }
    return {
      id: credential.id,
      rawId: toBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || null,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: response,
    };
  }

  async function postJSON(url, body) {
    var res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    });
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  async function register() {
    var token = decodeURIComponent(location.hash.slice(1)).trim().toLowerCase();
    if (!token) throw new Error("This page needs the full invite link. Open the link you were sent.");
    // Invite tokens are 64 hex characters; anything else was damaged in transit.
    if (!/^[0-9a-f]{64}$/.test(token)) {
      throw new Error(
        "This invite link is incomplete (" + token.length + " of 64 characters arrived). " +
        "Ask for the link again, and send it by AirDrop or copy it whole."
      );
    }
    var start = await postJSON("/auth/register/options", { invite_token: token });
    var o = start.options;
    var credential = await navigator.credentials.create({
      publicKey: Object.assign({}, o, {
        challenge: toBytes(o.challenge),
        user: Object.assign({}, o.user, { id: toBytes(o.user.id) }),
        excludeCredentials: descriptors(o.excludeCredentials),
      }),
    });
    return postJSON("/auth/register/verify", {
      challenge_id: start.challenge_id,
      credential: serialize(credential),
    });
  }

  async function login() {
    var start = await postJSON("/auth/login/options");
    var o = start.options;
    var credential = await navigator.credentials.get({
      publicKey: Object.assign({}, o, {
        challenge: toBytes(o.challenge),
        allowCredentials: descriptors(o.allowCredentials),
      }),
    });
    return postJSON("/auth/login/verify", {
      challenge_id: start.challenge_id,
      credential: serialize(credential),
    });
  }

  function message(err) {
    if (err && err.name === "NotAllowedError") return "The passkey request was cancelled or timed out.";
    if (err && err.name === "InvalidStateError") return "This device already has a passkey for your account.";
    return (err && err.message) || "Something went wrong. Please try again.";
  }

  document.addEventListener("click", async function (event) {
    var button = event.target.closest("[data-passkey]");
    if (!button) return;
    var status = document.getElementById("passkey-status");
    if (!window.PublicKeyCredential) {
      status.textContent = "This browser doesn't support passkeys. Try an up-to-date Safari or Chrome.";
      return;
    }
    button.disabled = true;
    status.textContent = "";
    try {
      var done = await (button.dataset.passkey === "register" ? register() : login());
      // Replace history so Back doesn't return to the invite link.
      location.replace(done.redirect);
    } catch (err) {
      status.textContent = message(err);
      button.disabled = false;
    }
  });
})();
