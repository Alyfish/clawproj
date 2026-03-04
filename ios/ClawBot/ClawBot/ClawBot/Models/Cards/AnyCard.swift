import Foundation

// MARK: - AnyCard
// Maps to shared/types/cards.ts → AnyCard (discriminated union)
// Uses `type` field as discriminator: "flight" | "house" | "pick" | "doc"

enum AnyCard: Identifiable, Equatable {
    case flight(FlightCard)
    case house(HouseCard)
    case pick(PickCard)
    case doc(DocCard)
    case base(BaseCard)

    var id: String {
        switch self {
        case .flight(let card): return card.id
        case .house(let card): return card.id
        case .pick(let card): return card.id
        case .doc(let card): return card.id
        case .base(let card): return card.id
        }
    }
}

// MARK: - Codable

extension AnyCard: Codable {
    private enum CodingKeys: String, CodingKey {
        case type
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(String.self, forKey: .type)

        // try? + fallback: if typed decoder fails (missing fields from browser-scraped data),
        // degrade gracefully to GenericCardView via BaseCard instead of dropping the card.
        switch type {
        case "flight":
            if let card = try? FlightCard(from: decoder) {
                self = .flight(card)
            } else {
                self = .base(try BaseCard(from: decoder))
            }
        case "house":
            if let card = try? HouseCard(from: decoder) {
                self = .house(card)
            } else {
                self = .base(try BaseCard(from: decoder))
            }
        case "pick":
            if let card = try? PickCard(from: decoder) {
                self = .pick(card)
            } else {
                self = .base(try BaseCard(from: decoder))
            }
        case "doc":
            if let card = try? DocCard(from: decoder) {
                self = .doc(card)
            } else {
                self = .base(try BaseCard(from: decoder))
            }
        default:
            self = .base(try BaseCard(from: decoder))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)

        switch self {
        case .flight(let card):
            try container.encode("flight", forKey: .type)
            try card.encode(to: encoder)
        case .house(let card):
            try container.encode("house", forKey: .type)
            try card.encode(to: encoder)
        case .pick(let card):
            try container.encode("pick", forKey: .type)
            try card.encode(to: encoder)
        case .doc(let card):
            try container.encode("doc", forKey: .type)
            try card.encode(to: encoder)
        case .base(let card):
            // BaseCard encodes its own `type` field — no double-encoding
            try card.encode(to: encoder)
        }
    }
}

// MARK: - Computed Properties

extension AnyCard {
    /// Returns the BaseCard if this is a `.base` case, nil otherwise.
    var baseCard: BaseCard? {
        if case .base(let card) = self { return card }
        return nil
    }

    /// Returns the card's type discriminator string.
    var cardType: String {
        switch self {
        case .flight: return "flight"
        case .house: return "house"
        case .pick: return "pick"
        case .doc: return "doc"
        case .base(let card): return card.type
        }
    }
}

// MARK: - Mock Data

extension AnyCard {
    static let mockCards: [AnyCard] = [
        .flight(FlightCard.mockDefault),
        .flight(FlightCard.mockCheapest),
        .house(HouseCard.mockClean),
        .house(HouseCard.mockRedFlags),
        .pick(PickCard.mockFavorable),
        .doc(DocCard.mockDocument),
        .base(BaseCard.mockShopifyOrder),
    ]
}
