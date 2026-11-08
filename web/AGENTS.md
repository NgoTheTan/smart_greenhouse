# Hướng dẫn Coding Assistant – `web/`

Thư mục này chứa ứng dụng **Web Console (React 18 + Vite + TypeScript + React Query + Recharts v3 + PWA/Web Push)**.

- Tài liệu chi tiết:
  - [FEATURE_WEB_CONSOLE_UI.md](./FEATURE_WEB_CONSOLE_UI.md) — 9 trang giao diện tiếng Việt, biểu đồ Recharts v3, WebSocket client, RBAC trên UI.
  - [FEATURE_PWA_AND_WEB_PUSH.md](./FEATURE_PWA_AND_WEB_PUSH.md) — `manifest.json`, `sw.js`, đăng ký VAPID theo cú bấm người dùng, hướng dẫn iOS.
- Bất biến quan trọng:
  - Giao diện Web và thông báo **100% tiếng Việt**, thiết kế **responsive** cho cả laptop và điện thoại (không xây app di động native).
  - **Không đặt file `.md`** vào `web/public/` (vì `web/public/` được Vite copy nguyên vào `web/dist/` để Caddy phục vụ).
  - Dùng **Recharts v3** (`^3.10.1`) và **React 18** (`^18.3.1`) theo `docs/DECISIONS.md`.
  - Luôn kiểm tra build sạch bằng `npm run build --prefix web` (`tsc -b && vite build`).
