import Foundation

// MARK: - AnyCard
// Maps to shared/types/cards.ts → AnyCard (discriminated union)
// Uses `type` field as discriminator: "flight" | "house" | "pick" | "doc"

enum AnyCard: Identifiable, Equatable {
    case flight(FlightCard)
    case house(HouseCard)
    case pick(PickCard)
    case doc(DocCard)

    var id: String {
        switch self {
        case .flight(let card): return card.id
        case .house(let card): return card.id
        case .pick(let card): return card.id
        case .doc(let card): return card.id
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

        switch type {
        case "flight":
            self = .flight(try FlightCard(from: decoder))
        case "house":
            self = .house(try HouseCard(from: decoder))
        case "pick":
            self = .pick(try PickCard(from: decoder))
        case "doc":
            self = .doc(try DocCard(from: decoder))
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .type,
                in: container,
                debugDescription: "Unknown card type: \(type)"
            )
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
    ]
}
