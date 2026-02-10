---
title: "TIL: uv needs SSL_CERT_FILE on some systems"
date: 2026-02-10T15:30:00
type: note
tags: [python, uv, til]
draft: false
---

If you get `UnknownIssuer` TLS errors with uv, set:

```bash
export SSL_CERT_FILE=/opt/homebrew/etc/openssl@3/cert.pem
```

This happens when your system's certificate store isn't where uv's bundled TLS library expects it.
