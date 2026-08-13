# Backend contract

The bridge listens on 127.0.0.1:8787. ComfyUI listens on 127.0.0.1:8190.
The public health response includes:

- ok
- version
- local app and ComfyUI ports
- model and node readiness flags
- active job and sequence identifiers

Mutation routes require the CSRF token returned by /api/session. Keep
TrustedHostMiddleware, security headers, upload size limits, and path
validation when adding routes.
