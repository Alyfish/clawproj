import Foundation

// MARK: - Rent
// Maps to shared/types/cards.ts → Rent

struct Rent: Codable, Equatable {
    let amount: Double
    let currency: String
    /// e.g. "month", "week"
    let period: String

    /// e.g. "$2,400/mo" or "$600/wk"
    var formatted: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        let amountStr = formatter.string(from: NSNumber(value: amount)) ?? "\(Int(amount))"

        let suffix: String
        switch period {
        case "month": suffix = "/mo"
        case "week": suffix = "/wk"
        default: suffix = "/\(period)"
        }

        if currency == "USD" {
            return "$\(amountStr)\(suffix)"
        }
        return "\(currency) \(amountStr)\(suffix)"
    }
}

// MARK: - Commute
// Maps to shared/types/cards.ts → Commute

struct Commute: Codable, Equatable {
    let destination: String
    /// e.g. "25 min"
    let time: String
    /// e.g. "driving", "transit", "walking"
    let mode: String
}

// MARK: - HouseCard
// Maps to shared/types/cards.ts → HouseCard

struct HouseCard: Identifiable, Codable, Equatable {
    let id: String
    let address: String
    let rent: Rent
    let bedrooms: Int
    /// e.g. "750 sqft"
    let area: String
    let commute: Commute
    let leaseTerms: String
    /// ISO 8601 date
    let moveInDate: String
    let requiredDocs: [String]
    /// Auto-detected issues: unusual deposits, hidden fees, etc.
    let redFlags: [String]
    let source: String
    let listingUrl: String

    /// Returns "Studio" for 0 bedrooms, otherwise "N BR".
    var bedroomLabel: String {
        bedrooms == 0 ? "Studio" : "\(bedrooms) BR"
    }
}

// MARK: - Mock Data

extension HouseCard {
    static let mockClean = HouseCard(
        id: "house-1",
        address: "742 Valencia St, Apt 3B, San Francisco, CA 94110",
        rent: Rent(amount: 2400, currency: "USD", period: "month"),
        bedrooms: 1,
        area: "750 sqft",
        commute: Commute(destination: "Financial District", time: "25 min", mode: "transit"),
        leaseTerms: "12-month lease, month-to-month after",
        moveInDate: "2026-04-01",
        requiredDocs: ["Pay stubs (3 months)", "Photo ID", "Credit report"],
        redFlags: [],
        source: "Zillow",
        listingUrl: "https://example.com/listing/house-1"
    )

    static let mockRedFlags = HouseCard(
        id: "house-2",
        address: "1200 Market St, Unit 8, San Francisco, CA 94103",
        rent: Rent(amount: 1800, currency: "USD", period: "month"),
        bedrooms: 0,
        area: "400 sqft",
        commute: Commute(destination: "SOMA Office", time: "10 min", mode: "walking"),
        leaseTerms: "6-month minimum, $500 early termination fee",
        moveInDate: "2026-03-15",
        requiredDocs: ["Pay stubs (6 months)", "Photo ID", "Bank statements", "Employer letter"],
        redFlags: [
            "Security deposit is 3x rent ($5,400) — above typical 1-2x",
            "Early termination fee not disclosed upfront",
            "No in-unit laundry despite listing claim"
        ],
        source: "Craigslist",
        listingUrl: "https://example.com/listing/house-2"
    )
}
