import Foundation

// MARK: - WSMessageType
// Maps to shared/types/gateway.ts → WSMessage.type

enum WSMessageType: String, Codable {
    case req
    case res
    case event
}

// MARK: - WSMessage
// Maps to shared/types/gateway.ts → WSMessage

struct WSMessage: Codable {
    let type: WSMessageType
    /// Correlation ID for req/res pairs.
    let id: String?
    /// Method name for requests: chat.send, chat.history, approval.resolve, task.stop
    let method: String?
    /// Event name for server-pushed events.
    let event: String?
    let payload: [String: AnyCodable]?

    init(
        type: WSMessageType,
        id: String? = nil,
        method: String? = nil,
        event: String? = nil,
        payload: [String: AnyCodable]? = nil
    ) {
        self.type = type
        self.id = id
        self.method = method
        self.event = event
        self.payload = payload
    }

    static func request(
        method: String,
        id: String,
        payload: [String: AnyCodable]? = nil
    ) -> WSMessage {
        WSMessage(type: .req, id: id, method: method, payload: payload)
    }
}

// MARK: - AnyCodable
// Type-erased Codable wrapper for heterogeneous JSON payloads.

struct AnyCodable: Codable, Equatable {

    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    // MARK: Codable

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map(\.value)
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues(\.value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "AnyCodable: unsupported JSON value"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            throw EncodingError.invalidValue(
                value,
                EncodingError.Context(
                    codingPath: encoder.codingPath,
                    debugDescription: "AnyCodable: unsupported type \(type(of: value))"
                )
            )
        }
    }

    // MARK: Equatable — compare via JSON-encoded bytes

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        guard
            let lhsData = try? encoder.encode(lhs),
            let rhsData = try? encoder.encode(rhs)
        else { return false }
        return lhsData == rhsData
    }

    // MARK: Convenience accessors

    var stringValue: String? { value as? String }
    var intValue: Int? { value as? Int }
    var doubleValue: Double? { value as? Double }
    var boolValue: Bool? { value as? Bool }
    var arrayValue: [Any]? { value as? [Any] }
    var dictValue: [String: Any]? { value as? [String: Any] }
    var isNull: Bool { value is NSNull }
}
