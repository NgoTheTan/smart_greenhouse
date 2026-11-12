# Feature: PWA & Web Push Notifications (`web/public/`, `web/src/lib/push.ts`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.7, 9, 10, 13.1, 13.2, 16 (M3, M4).

## 1. Mục tiêu & Phạm vi

Biến GreenHub Web Console thành **Progressive Web App (PWA)** có thể cài lên màn hình chính điện thoại/desktop và nhận thông báo đẩy **Web Push (VAPID)** ngay cả khi người dùng đóng tab hoặc đóng trình duyệt, dùng chuẩn Web Push API (không qua Firebase/FCM).

- **Ngoài phạm vi:** Không xây app Android/iOS native; không dùng FCM/Firebase SDK; không dùng Telegram bot.

## 2. Trạng thái hiện thực trong repo

- **Đã có sẵn (M2/M3 nền):**
  - `web/public/manifest.json`: tên `"GreenHub – Nhà kính thông minh"`, `display: "standalone"`, `theme_color: "#2e7d32"`, `lang: "vi"`, icons (`icon.svg`, `icon-192.png`, `icon-512.png`).
  - `web/public/sw.js`: Service Worker xử lý `install` (`skipWaiting`), `activate` (`clients.claim`), sự kiện `push` (parse JSON `{title, body, tag, severity, url}`, bật `requireInteraction: d.severity === 'critical'`, hiển thị icon `/icon-192.png`) và `notificationclick` (đóng thông báo, mở `clients.openWindow(url)`).
  - `web/index.html`: cần đảm bảo đã liên kết `<link rel="manifest" href="/manifest.json">` và `<meta name="theme-color" ...>`, đồng thời đăng ký `navigator.serviceWorker.register('/sw.js')` trong `web/src/main.tsx` (hoặc khi app mount).
  - `web/src/lib/push.ts`: hàm `subscribePush()` thực hiện đúng chuẩn `Notification.requestPermission()` → `GET /api/push/public-key` → `pushManager.subscribe(...)` → `POST /api/push/subscribe`.
  - `deploy/caddy/Caddyfile`: đã cấu hình `@sw path /sw.js /manifest.json` kèm `header @sw Cache-Control "no-cache"` để trình duyệt luôn nhận bản Service Worker mới nhất.

## 3. Chi tiết kỹ thuật & Ràng buộc Trình duyệt (MUST)

### 3.1 Yêu cầu HTTPS
- Service Worker và Push API **BẮT BUỘC** chạy trong Secure Context (`HTTPS`).
- Ngoại lệ duy nhất được trình duyệt miễn: `http://localhost` (hoặc `127.0.0.1`) khi phát triển trên laptop.
- Để thử Web Push trên điện thoại thật:
  - Ở dev laptop: điện thoại không truy cập được `localhost` của laptop; phải dùng Caddy HTTPS + chứng chỉ hoặc tốt nhất là thử ở M4 qua tên miền riêng hoặc DuckDNS + Let's Encrypt trên VPS Linux.
  - Khi chạy `npm run dev` (Vite port 5173): cần đảm bảo `sw.js` và `manifest.json` trong `web/public/` phục vụ đúng tại root `/` và `/api/push/*` được proxy tới backend.

### 3.2 Đăng ký Service Worker & Xin quyền (User Gesture)
- **Đăng ký `sw.js`:** gọi `navigator.serviceWorker.register('/sw.js')` khi khởi động app (nếu `'serviceWorker' in navigator`).
- **Xin quyền Push (`subscribePush`):** **TUYỆT ĐỐI KHÔNG** gọi `Notification.requestPermission()` tự động lúc vừa tải trang (trình duyệt hiện đại sẽ tự chặn hoặc đánh dấu spam!). Phải gắn vào sự kiện `onClick` của nút bấm người dùng trong trang Cài đặt thông báo.
- **Hủy đăng ký (`unsubscribePush`):**
  1. Lấy `const sub = await reg.pushManager.getSubscription()`.
  2. Nếu có `sub`, gọi `DELETE /api/push/subscribe` gửi `sub.endpoint` lên backend, sau đó gọi `await sub.unsubscribe()`.

### 3.3 Payload `sw.js` & Điều hướng khi bấm thông báo
- Payload từ `worker/notify.py` (`pywebpush`):
  ```json
  {
    "title": "CẢNH BÁO: Nguy cơ nấm bệnh",
    "body": "CẢNH BÁO: Nguy cơ nấm bệnh – Luống Dâu tây (Zone 2): VPD 0.14 kPa, RH 94%. Quạt đã được bật.",
    "tag": "DISEASE_RISK:<zone_id>",
    "severity": "critical",
    "url": "/zones/<zone_id>"
  }
  ```
- **Cơ chế `tag`:** sử dụng `dedupe_key` làm `tag` giúp trình duyệt gom/cập nhật thông báo cùng một sự cố thay vì tạo hàng chục banner trùng lặp.
- **Cơ chế `notificationclick`:** nếu đã có tab Web Console đang mở ở cùng origin, có thể ưu tiên `client.focus()` + `client.navigate(url)` hoặc dùng `clients.openWindow(e.notification.data.url)` (theo spec 10).

### 3.4 Hướng dẫn iOS & Giới hạn hệ điều hành (MUST ghi trên UI)
- **iOS 16.4 trở lên:** Safari trên iOS **chỉ** cấp quyền `Notification` & `PushManager` khi trang web đã được người dùng thêm vào màn hình chính (**Share → Add to Home Screen**) và mở từ ứng dụng PWA đó. Trang `/settings/notifications` phải hiển thị hướng dẫn trực quan bước này.
- **Giới hạn đã biết (spec 10):** Web Push phụ thuộc dịch vụ đẩy của trình duyệt (FCM/APNs/Mozilla Push), không đảm bảo 100% thời gian thực và có thể bị chế độ Không làm phiền (DND) ẩn → do đó hệ thống vẫn giữ bắt buộc **Email leo thang** và **Buzzer trên Gateway**.

## 4. Kiểm tra & Xác nhận

- Sinh khoá VAPID: `python -m tools.gen_vapid` và điền `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` vào `.env`.
- Kiểm thử M3 trên `https://localhost` (hoặc `http://localhost:5173`): bật push → tắt tab → tạo alert `DISEASE_RISK` → thông báo hệ điều hành bật lên → click vào mở đúng `/zones/{id}`.
- Kiểm thử M4 trên điện thoại thật (Android Chrome & iOS Safari Add to Home Screen) qua HTTPS (tên miền riêng hoặc DuckDNS trên VPS).
