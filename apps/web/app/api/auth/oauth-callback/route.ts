import { NextResponse } from "next/server";

/**
 * OAuth2 popup callback receiver that posts the result to its same-origin opener
 * and waits for an acknowledgement before closing.
 */
export async function GET() {
  const html = `<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="utf-8" />
  <title>Menyelesaikan Login OAuth — RADAR AI</title>
</head>
<body style="background:#0b1220;color:#e2e8f0;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
  <p>Memverifikasi kredensial OAuth…</p>
  <script>
    (function () {
      var hash = window.location.hash ? window.location.hash.substring(1) : "";
      var params = new URLSearchParams(hash || window.location.search);
      var payload = {
        type: "RADAR_GOOGLE_OAUTH_RESULT",
        state: params.get("state") || "",
        idToken: params.get("id_token") || "",
        accessToken: params.get("access_token") || "",
        error: params.get("error_description") || params.get("error") || ""
      };
      if (!window.opener || window.opener === window) {
        document.querySelector("p").textContent =
          "Jendela utama tidak terhubung. Tutup jendela ini lalu coba login kembali.";
        return;
      }

      window.addEventListener("message", function onAcknowledgement(event) {
        if (event.origin !== window.location.origin || event.source !== window.opener) return;
        var acknowledgement = event.data;
        if (
          !acknowledgement ||
          acknowledgement.type !== "RADAR_GOOGLE_OAUTH_ACK" ||
          acknowledgement.state !== payload.state
        ) return;
        window.removeEventListener("message", onAcknowledgement);
        window.close();
      });
      window.opener.postMessage(payload, window.location.origin);
      window.setTimeout(function () {
        document.querySelector("p").textContent =
          "Respons login belum diterima jendela utama. Tutup jendela ini lalu coba kembali.";
      }, 10000);
    })();
  </script>
</body>
</html>`;

  return new NextResponse(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store, max-age=0",
      "Cross-Origin-Opener-Policy": "unsafe-none",
      "X-Frame-Options": "DENY",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
