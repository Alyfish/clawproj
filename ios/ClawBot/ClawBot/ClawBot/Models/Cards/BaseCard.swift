import Foundation

// MARK: - CardRanking
// Maps to shared/types/cards.ts → BaseCard.ranking

struct CardRanking: Codable, Equatable {
    let label: String
    let reason: String
}

// MARK: - BaseCard
// Maps to shared/types/cards.ts → BaseCard

struct BaseCard: Codable, Identifiable, Equatable {
    let id: String
    /// Free-form type string — NOT an enum. Typed cards narrow this to a literal.
    let type: String
    let title: String
    let subtitle: String?
    /// Arbitrary key-value metadata. Defaults to `[:]` if missing from JSON.
    let metadata: [String: AnyCodable]
    let actions: [CardAction]?
    let ranking: CardRanking?
    let source: String?
    /// ISO 8601
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, type, title, subtitle, metadata, actions, ranking, source, createdAt
    }

    init(
        id: String,
        type: String,
        title: String,
        subtitle: String? = nil,
        metadata: [String: AnyCodable] = [:],
        actions: [CardAction]? = nil,
        ranking: CardRanking? = nil,
        source: String? = nil,
        createdAt: String
    ) {
        self.id = id
        self.type = type
        self.title = title
        self.subtitle = subtitle
        self.metadata = metadata
        self.actions = actions
        self.ranking = ranking
        self.source = source
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        type = try container.decode(String.self, forKey: .type)
        title = try container.decode(String.self, forKey: .title)
        subtitle = try container.decodeIfPresent(String.self, forKey: .subtitle)
        metadata = try container.decodeIfPresent([String: AnyCodable].self, forKey: .metadata) ?? [:]
        actions = try container.decodeIfPresent([CardAction].self, forKey: .actions)
        ranking = try container.decodeIfPresent(CardRanking.self, forKey: .ranking)
        source = try container.decodeIfPresent(String.self, forKey: .source)
        createdAt = try container.decode(String.self, forKey: .createdAt)
    }
}

// MARK: - Helpers

extension BaseCard {
    /// Metadata keys sorted alphabetically, excluding underscore-prefixed internal keys.
    var visibleMetadataKeys: [String] {
        metadata.keys
            .filter { !$0.hasPrefix("_") }
            .sorted()
    }

    /// Formats a metadata key for display: replace "_" with " ", capitalize each word.
    static func formatKey(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst().lowercased() }
            .joined(separator: " ")
    }

    /// Returns true if the key matches a "money" pattern (for green highlighting).
    static func isMoneyKey(_ key: String) -> Bool {
        let lower = key.lowercased()
        return ["price", "cost", "amount", "total"].contains(where: lower.contains)
    }

    /// Returns true if the key matches a "warning" pattern (for red highlighting).
    static func isWarningKey(_ key: String) -> Bool {
        let lower = key.lowercased()
        return ["warning", "flag", "risk", "error"].contains(where: lower.contains)
    }
}

// MARK: - Mock Data

extension BaseCard {
    static let mockShopifyOrder = BaseCard(
        id: "base-order-1",
        type: "shopify_order",
        title: "Order #1042 — Confirmed",
        subtitle: "3 items shipped via USPS Priority",
        metadata: [
            "items": AnyCodable([
                ["name": "Wireless Earbuds", "qty": 1, "price": 79.99] as [String: Any],
                ["name": "USB-C Cable", "qty": 2, "price": 12.99] as [String: Any],
                ["name": "Phone Case", "qty": 1, "price": 24.99] as [String: Any]
            ] as [[String: Any]]),
            "total": AnyCodable(130.96),
            "customer": AnyCodable("alex@example.com"),
            "status": AnyCodable("shipped"),
            "tracking": AnyCodable("9400111899223456789012")
        ],
        actions: [
            CardAction(id: "act-1", label: "Track Package", type: .link, url: "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223456789012", approvalAction: nil, payload: nil),
            CardAction(id: "act-2", label: "Request Refund", type: .approve, url: nil, approvalAction: "submit", payload: nil)
        ],
        ranking: CardRanking(label: "Recent Order", reason: "Placed 2 hours ago, already shipped"),
        source: "Shopify",
        createdAt: "2026-03-01T14:30:00Z"
    )

    static let mockCryptoPrice = BaseCard(
        id: "base-crypto-1",
        type: "crypto_price",
        title: "Bitcoin (BTC)",
        subtitle: "Last updated just now",
        metadata: [
            "price": AnyCodable(67432.18),
            "24h_change": AnyCodable(-2.4),
            "market_cap": AnyCodable("$1.32T"),
            "volume_24h": AnyCodable("$28.5B"),
            "symbol": AnyCodable("BTC")
        ],
        actions: [
            CardAction(id: "act-3", label: "View Chart", type: .link, url: "https://coinmarketcap.com/currencies/bitcoin/", approvalAction: nil, payload: nil)
        ],
        source: "CoinMarketCap",
        createdAt: "2026-03-02T09:15:00Z"
    )

    static let mockMinimal = BaseCard(
        id: "base-minimal-1",
        type: "note",
        title: "Quick Note",
        createdAt: "2026-03-02T12:00:00Z"
    )
}
