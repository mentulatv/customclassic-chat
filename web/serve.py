"""The website on this computer, for trying it: python serve.py, then http://localhost:8099.

It sends the two headers that let the page use several threads for text recognition when the
graphics card can't (COOP/COEP: the page is "cross-origin isolated"). A host serving the site
(ccc.mentula.tv) should send the same two."""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "credentialless")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(Path(__file__).parent)))
    print(f"CustomClassic Chat on http://localhost:{port}", flush=True)
    server.serve_forever()
