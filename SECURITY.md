# Security

This is a local prototype without authentication, authorization, TLS, rate limiting, or multi-user isolation.

- Keep the default bind address `127.0.0.1`.
- Do not expose the server directly to the public internet.
- Do not commit local character files, session data, generated media, logs, tokens, or environment files.
- Treat LM Studio and ComfyUI endpoints as trusted local services.

For hosted use, add authentication, request limits, isolated storage, a controlled generation queue, and an authenticated GPU backend before deployment.
