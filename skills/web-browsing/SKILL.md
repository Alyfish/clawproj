---
name: web-browsing
description: Tool selection for web tasks — curl-first reads, browser for interactive actions, direct search URLs, parsing patterns.
tools: [bash_execute, browser]
approval_actions: [pay, submit]
version: "1.0.0"
author: ClawBot
tags: [web, browsing, curl, search, scraping, shopping, amazon, nike, ebay]
---

# Web Browsing

## Tool Selection — ALWAYS follow this order

### 1. bash_execute + curl (0.01-1s) — DEFAULT for all reads
```bash
curl -sL "<URL>" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml" \
  -H "Accept-Language: en-US,en;q=0.9" \
  --max-time 10 --max-redirs 5
```

When curl returns <500 bytes, or contains "Enable JavaScript" / "captcha" / "please verify" → switch to browser.

### 2. browser via CDP (1-15s) — ONLY for interactive/authenticated actions

Add to cart, checkout, form submission, clicking JS buttons, anything needing cookies.

Rules when using browser:
- Navigate returns page state. Never take a standalone snapshot after navigate.
- Batch: type + click + submit in one call.
- Use action="authenticate" when hitting a login wall.

## Direct URLs

| Site | Search URL |
|------|-----------|
| amazon.com | `https://www.amazon.com/s?k={q}` |
| stockx.com | `https://stockx.com/search?s={q}` |
| goat.com | `https://www.goat.com/search?query={q}` |
| nike.com | `https://www.nike.com/w?q={q}` |
| ebay.com | `https://www.ebay.com/sch/i.html?_nkw={q}` |
| walmart.com | `https://www.walmart.com/search?q={q}` |
| target.com | `https://www.target.com/s?searchTerm={q}` |
| footlocker.com | `https://www.footlocker.com/search?query={q}` |
| grailed.com | `https://www.grailed.com/shop?query={q}` |
| bestbuy.com | `https://www.bestbuy.com/site/searchpage.jsp?st={q}` |
| Unknown | `https://{domain}/search?q={q}` then homepage fallback |

Replace spaces with `+`.

## Parsing Patterns

Amazon search (bash):
```bash
curl -sL "https://www.amazon.com/s?k=calabrian+chilis" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" | \
  python3 -c "
import sys,re,json; h=sys.stdin.read()
results=[]
for m in re.finditer(r'data-asin=\"(\w{10})\"',h):
    a=m.group(1)
    if a and a not in [r['asin'] for r in results]:
        results.append({'asin':a,'url':f'https://www.amazon.com/dp/{a}'})
    if len(results)>=5: break
print(json.dumps(results))
"
```

Product page (bash):
```bash
curl -sL "$URL" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36" | \
  python3 -c "
import sys,re,json; h=sys.stdin.read()
t=re.search(r'<title>([^<]+)',h)
p=list(set(re.findall(r'\\\$[\d,]+\.?\d*',h)))[:5]
print(json.dumps({'title':t.group(1).strip() if t else '','prices':p}))
"
```

## Iteration Budget

| Task | Max steps | Tools |
|------|-----------|-------|
| Read-only | 1-3 | All bash |
| Add to cart | 3-5 | 2 bash + 1-2 browser |
| Checkout | 5-8 | 2 bash + 3-5 browser |
| HARD LIMIT | 10 | Stop, report failure |

## Example: "add calabrian chilis to my Amazon cart"

1. (bash <1s) curl search URL → parse ASINs
2. (bash <1s) curl product page → verify name + price
3. (browser ~10s) navigate product page, click "Add to Cart"
4. (browser ~3s) verify "Added to Cart" confirmation
→ 4 steps, ~15s total. NOT 16 browser iterations.
