---
name: web-auth
description: Web authentication — early detection, credential pre-warming, login strategies, 2FA handling.
tools: [bash_execute, browser]
approval_actions: [submit]
version: "1.0.0"
author: ClawBot
tags: [auth, login, credentials, 2fa, session, cookies]
---

# Web Authentication

## Early detection

If task involves: cart, buy, purchase, checkout, order, wishlist, save, my account, my orders → REQUIRES AUTH. Pre-warm credentials BEFORE first tool call.

## Auth strategy

1. **Pre-warm**: pre_warm_auth(domain) fetches iOS credentials over WebSocket. 0 browser cost.
2. **Session cache**: reuse previous session cookies. 0 cost.
3. **Direct login URL**: navigate to /ap/signin (Amazon), /login (most sites). NOT homepage.
4. **Auto-fill**: use iOS credentials via CDP page.type(). Scope form detection to `<form>` with password field.
5. **Interactive fallback**: show user the LOGIN PAGE (not homepage) in Browser Login sheet.
6. **2FA**: TOTP auto-generated. SMS/push on user's phone.

## Login wall detection

During browser steps, immediately trigger auth if:
- URL contains /login, /signin, /auth, /ap/signin, /sso
- Visible password field appeared
- Page text: "sign in", "log in", "create account"

## Known login URLs

| Site | Login URL |
|------|-----------|
| amazon.com | /ap/signin |
| stockx.com | /login |
| goat.com | /login |
| nike.com | /login |
| ebay.com | signin.ebay.com |
| walmart.com | /account/login |
| target.com | /login |
| grailed.com | /login |
| footlocker.com | /login |
| bestbuy.com | /identity/signin |
| Unknown | /login |
