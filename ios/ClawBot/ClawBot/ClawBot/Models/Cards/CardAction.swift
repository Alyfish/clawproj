import Foundation

// MARK: - CardActionType
// Maps to shared/types/cards.ts → CardAction.type

enum CardActionType: String, Codable, CaseIterable {
    case link, approve, dismiss, copy, custom
}

// MARK: - CardAction
// Maps to shared/types/cards.ts → CardAction

struct CardAction: Codable, Identifiable, Equatable {
    let id: String
    let label: String
    let type: CardActionType
    /// URL to open for `.link` actions.
    let url: String?
    /// Approval action string for `.approve` actions (maps to ApprovalAction raw value).
    let approvalAction: String?
    /// Arbitrary payload for `.custom` actions.
    let payload: [String: AnyCodable]?

    enum CodingKeys: String, CodingKey {
        case id, label, type, url, approvalAction, payload
    }
}
