# Apartment Red Flag Detection Rules

Companion document for the `apartment-search` skill. These rules help the agent detect scams, misleading listings, and problematic rental situations.

---

## Red Flag Patterns

### Critical Severity (+3 points each)

**RF-01: Money Requested Before Viewing**
- Landlord asks for deposit, application fee, or "holding fee" before you can see the unit
- Example: "Send $500 via Zelle to hold the apartment, then we'll schedule a tour"
- Legitimate landlords show the unit first, then collect application fees
- Exception: Some large property management companies charge an application fee after a tour but before a lease — this is normal if the amount is $25-75

**RF-02: Wire Transfer / Gift Card Payment**
- Any request to pay via wire transfer, Western Union, MoneyGram, gift cards, or cryptocurrency
- Example: "Please wire the first month's rent to this account to secure the unit"
- Legitimate landlords accept checks, ACH, or credit cards through a property management portal

**RF-03: Overseas Landlord / Can't Show Unit**
- Landlord claims to be out of the country, deployed military, missionary, etc.
- Offers to mail keys after receiving payment
- Example: "I'm currently in London for work and can't show the apartment, but I can FedEx the keys once I receive the deposit"
- Legitimate absent landlords use local property managers

### High Severity (+2 points each)

**RF-04: Price Below 60% of Area Median**
- Rent significantly below comparable listings in the same area
- Use the city tier median rents table below to calibrate
- Example: 2BR in Manhattan listed at $1,200/mo (median: $3,800+)
- Some legitimate below-market rentals exist (rent-controlled, subsidized, family deals) but they are rare and should still be flagged for user awareness

**RF-05: Cash Only / No Lease Mentioned**
- Listing mentions cash, Venmo, Zelle, or PayPal as only payment methods
- No mention of a formal lease agreement
- Example: "Rent is $900/mo cash, month-to-month, no lease needed"
- Legitimate rentals have written lease agreements and accept traceable payments

**RF-06: Application Fee Before Viewing**
- Charges an application fee ($100+) before you can see the apartment
- Small application fees ($25-75) after a showing are normal
- Example: "Submit your application with $200 fee to be considered for a viewing"

**RF-07: Below-Market New Construction**
- Brand new or recently renovated building with rent 40%+ below similar new buildings
- Example: "Luxury 2BR with rooftop pool, brand new build, only $1,100/mo" in a market where similar units are $2,200+

### Medium Severity (+1 point each)

**RF-08: No Photos Provided**
- Listing has zero photos or only stock/generic images
- Reverse image search can detect stolen photos from other listings
- Legitimate landlords provide at least 3-5 photos of the actual unit

**RF-09: Vague or Missing Address**
- No street number, only neighborhood or cross streets
- Example: "Beautiful apartment near Central Park" with no specific address
- Legitimate listings include the exact address or at minimum the building name

**RF-10: Personal Email Only**
- Contact is a personal email (gmail, yahoo, hotmail, outlook) with no property management company
- No company name, website, or professional presence
- Not always a scam (individual landlords use personal email) but combined with other flags it raises concern

**RF-11: Duplicate Listing Text**
- Description appears copied from another listing or is generic boilerplate
- Same photos appearing in multiple listings at different addresses
- Example: Identical 3-paragraph description found on 5 different Craigslist listings

**RF-12: Urgency Pressure / No Showing**
- "Available immediately, won't last, act now, first come first served"
- Combined with no option to schedule an in-person viewing
- Legitimate hot-market listings may be urgent but still offer showings

**RF-13: Suspicious Amenities for Price**
- Premium amenities (in-unit W/D, private parking, gym, pool, concierge) at well-below-market rent
- The combination of luxury features with bargain pricing is a common scam pattern

**RF-14: Listing Repost Churn**
- Same listing reposted multiple times in a short period
- Often with slightly different titles or photos each time
- Indicates fake engagement or a listing that no one is actually renting

### Low Severity (+0.5 points each)

**RF-15: No Background/Credit Check**
- Landlord explicitly says no background check, no credit check, no references needed
- While tenant-friendly, this is unusual for legitimate landlords and can indicate a scam or illegal subletting

**RF-16: Unusual Deposit Structure**
- Deposit significantly above the typical 1-2 months rent
- Or deposit requested in a non-standard way (partial deposits, multiple installments to different accounts)

**RF-17: Mismatched Details**
- Square footage doesn't match bedroom count (e.g., "3BR, 400 sqft")
- Amenities list contradicts property type (e.g., "studio with 3 parking spots")

---

## Area Median Rent by City Tier

Use these medians to calibrate RF-04 (price below 60% of median). These are approximate 2025-2026 monthly rents for reference.

### Tier 1 — Major Metro ($2,500+ median)

| City | Studio | 1BR | 2BR | 3BR |
|------|--------|-----|-----|-----|
| New York (Manhattan) | $2,800 | $3,500 | $4,500 | $6,000 |
| New York (Brooklyn) | $2,300 | $2,900 | $3,600 | $4,500 |
| San Francisco | $2,500 | $3,200 | $4,000 | $5,200 |
| Los Angeles | $1,900 | $2,400 | $3,200 | $4,000 |
| Boston | $2,200 | $2,800 | $3,500 | $4,200 |
| Washington DC | $1,900 | $2,300 | $3,100 | $4,000 |
| Seattle | $1,800 | $2,200 | $2,900 | $3,600 |
| Miami | $1,800 | $2,300 | $3,000 | $3,800 |

### Tier 2 — Growing Metro ($1,800+ median)

| City | Studio | 1BR | 2BR | 3BR |
|------|--------|-----|-----|-----|
| Austin | $1,300 | $1,600 | $1,900 | $2,400 |
| Denver | $1,400 | $1,700 | $2,100 | $2,700 |
| Nashville | $1,300 | $1,600 | $1,900 | $2,400 |
| Portland | $1,200 | $1,500 | $1,900 | $2,400 |
| Minneapolis | $1,100 | $1,400 | $1,800 | $2,300 |
| Charlotte | $1,100 | $1,300 | $1,700 | $2,200 |
| Dallas | $1,100 | $1,400 | $1,800 | $2,300 |
| Chicago | $1,200 | $1,500 | $1,900 | $2,500 |
| Philadelphia | $1,100 | $1,400 | $1,700 | $2,200 |
| Atlanta | $1,200 | $1,500 | $1,800 | $2,300 |

### Tier 3 — Smaller Cities ($1,200+ median)

| City | Studio | 1BR | 2BR | 3BR |
|------|--------|-----|-----|-----|
| Indianapolis | $800 | $1,000 | $1,200 | $1,600 |
| Columbus | $800 | $1,000 | $1,300 | $1,700 |
| Kansas City | $750 | $950 | $1,200 | $1,500 |
| Pittsburgh | $800 | $1,000 | $1,200 | $1,600 |
| Memphis | $700 | $900 | $1,100 | $1,400 |
| Cleveland | $650 | $850 | $1,050 | $1,350 |
| Milwaukee | $750 | $950 | $1,200 | $1,500 |
| Richmond | $900 | $1,100 | $1,400 | $1,800 |
| Raleigh | $1,000 | $1,200 | $1,500 | $1,900 |
| Salt Lake City | $1,000 | $1,200 | $1,500 | $1,900 |

**60% threshold**: A listing is flagged if its rent is below 60% of the median for its city and bedroom count. For unlisted cities, estimate the tier and use the tier median.

---

## Scam Message Patterns

Watch for these phrases in listing descriptions or landlord messages:

### Payment Scam Indicators
- "Wire the deposit to..."
- "Send payment via Western Union / MoneyGram"
- "Pay with gift cards (iTunes, Amazon, Google Play)"
- "Use Bitcoin/crypto to pay rent"
- "Venmo/Zelle/CashApp only, no checks"
- "Send first and last month's rent to hold the unit"

### Absent Landlord Scam
- "I'm currently overseas / out of the country"
- "I'm deployed with the military"
- "I'm on a mission trip and can't show the unit"
- "I'll mail you the keys via FedEx/UPS"
- "My agent will handle everything remotely"

### Urgency / Pressure Tactics
- "This won't last — apply today"
- "Multiple applicants interested, decide now"
- "Special price only available for 24 hours"
- "I can hold it for you if you send a deposit today"
- "Price goes up tomorrow"

### Too-Good-to-Be-True
- "All utilities included" (at below-market rent)
- "No credit check, no background check, no references"
- "Move in today with just first month's rent"
- "Fully furnished luxury apartment" (at bargain price)

---

## Legitimate vs Suspicious: Side by Side

| Aspect | Legitimate Listing | Suspicious Listing |
|--------|-------------------|-------------------|
| **Price** | Within 20% of area median | 40-60%+ below median |
| **Photos** | 5-20 actual unit photos | 0 photos, stock images, or stolen photos |
| **Address** | Exact street address | Vague ("near downtown"), no street number |
| **Contact** | Property mgmt company, office phone | Personal Gmail only, no company name |
| **Viewing** | Offers in-person showing | Can't show unit, will mail keys |
| **Payment** | Check, ACH, or property portal | Cash, wire, gift cards, crypto |
| **Lease** | Written lease agreement provided | "No lease needed", handshake deal |
| **Application** | Fee ($25-75) after showing | Fee ($100+) before showing, or no fee at all |
| **Landlord** | Local, available for questions | Overseas, unavailable, "agent handles everything" |
| **Deposit** | 1-2 months rent, after lease signing | Deposit before viewing, unusual amounts |
| **Background** | Credit check + references | "No checks needed, anyone welcome" |
| **Description** | Specific details about unit | Generic/boilerplate, copied text |
| **Listing age** | Stable, not frequently reposted | Reposted multiple times in days |

---

## What To Do If a Scam Is Detected

When red flag score is 4+ or user reports a suspected scam:

### Immediate Steps
1. **Do NOT send money** — Stop all financial transactions with this listing
2. **Do NOT share personal info** — SSN, bank details, or ID documents
3. **Save evidence** — Screenshot the listing, save messages and emails
4. **Warn the user** — Clearly explain which red flags were detected and why

### Reporting
1. **FTC**: File a complaint at [reportfraud.ftc.gov](https://reportfraud.ftc.gov)
2. **FBI IC3**: Report internet fraud at [ic3.gov](https://www.ic3.gov)
3. **Platform**: Report the listing on the platform where it was found:
   - Zillow: Click "Report Listing" on the listing page
   - Craigslist: Click the "prohibited" flag on the listing
   - Apartments.com: Use "Report a Problem" link
   - Facebook Marketplace: Click "Report Listing"
4. **State AG**: File with your state Attorney General's consumer protection division
5. **Local police**: If money was lost, file a police report

### If Money Was Already Sent
1. Contact your bank immediately to attempt a reversal
2. If wire transfer: Contact the receiving bank
3. If gift cards: Contact the gift card company (Apple, Google, Amazon)
4. File a police report with the transaction details
5. Report to FTC and IC3 with all evidence
