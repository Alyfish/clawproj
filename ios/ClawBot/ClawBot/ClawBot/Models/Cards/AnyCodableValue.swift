import Foundation

// MARK: - AnyCodableValue
// Type-safe enum for heterogeneous JSON values in card metadata and payloads.
// Maps to TypeScript `unknown` / `Record<string, unknown>` in shared/types/cards.ts.
// Complements the existing AnyCodable struct (WSMessage.swift) which uses Any type erasure.
//
// Usage:
//   let val: AnyCodableValue = .dictionary(["price": .double(129.99), "nonstop": .bool(true)])
//   val["price"]?.displayString  // "129.99"
//   val["nonstop"]?.displayString // "Yes"
//
// Round-trip:
//   let data = try JSONEncoder().encode(AnyCodableValue.int(42))
//   let decoded = try JSONDecoder().decode(AnyCodableValue.self, from: data)
//   decoded == .int(42) // true

enum AnyCodableValue {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case array([AnyCodableValue])
    case dictionary([String: AnyCodableValue])
    case null
}

// MARK: - Codable

extension AnyCodableValue: Codable {

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            self = .null
            return
        }
        // Bool before Int — prevents JSON `true` from being coerced to `1`
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
            return
        }
        // Int before Double — keeps `42` as .int, not .double(42.0)
        if let value = try? container.decode(Int.self) {
            self = .int(value)
            return
        }
        if let value = try? container.decode(Double.self) {
            self = .double(value)
            return
        }
        if let value = try? container.decode(String.self) {
            self = .string(value)
            return
        }
        if let value = try? container.decode([AnyCodableValue].self) {
            self = .array(value)
            return
        }
        if let value = try? container.decode([String: AnyCodableValue].self) {
            self = .dictionary(value)
            return
        }

        throw DecodingError.dataCorruptedError(
            in: container,
            debugDescription: "AnyCodableValue: unsupported JSON type"
        )
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch self {
        case .null:
            try container.encodeNil()
        case .bool(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .string(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .dictionary(let value):
            try container.encode(value)
        }
    }
}

// MARK: - Display

extension AnyCodableValue {

    var displayString: String {
        switch self {
        case .string(let value):
            return value
        case .int(let value):
            return String(value)
        case .double(let value):
            let formatted = String(format: "%.2f", value)
            if formatted.hasSuffix(".00") {
                return String(formatted.dropLast(3))
            } else if formatted.hasSuffix("0") {
                return String(formatted.dropLast(1))
            }
            return formatted
        case .bool(let value):
            return value ? "Yes" : "No"
        case .array(let values):
            return values.map(\.displayString).joined(separator: ", ")
        case .dictionary(let dict):
            return dict.keys.sorted().map { key in
                "\(key): \(dict[key]!.displayString)"
            }.joined(separator: ", ")
        case .null:
            return "\u{2014}"
        }
    }
}

// MARK: - Accessors

extension AnyCodableValue {

    subscript(_ key: String) -> AnyCodableValue? {
        guard case .dictionary(let dict) = self else { return nil }
        return dict[key]
    }

    var unwrapped: Any {
        switch self {
        case .string(let value):     return value
        case .int(let value):        return value
        case .double(let value):     return value
        case .bool(let value):       return value
        case .array(let values):     return values.map(\.unwrapped)
        case .dictionary(let dict):  return dict.mapValues(\.unwrapped)
        case .null:                  return NSNull()
        }
    }
}

// MARK: - Equatable

extension AnyCodableValue: Equatable {
    static func == (lhs: AnyCodableValue, rhs: AnyCodableValue) -> Bool {
        switch (lhs, rhs) {
        case (.null, .null):                         return true
        case (.bool(let a), .bool(let b)):           return a == b
        case (.int(let a), .int(let b)):             return a == b
        case (.double(let a), .double(let b)):       return a == b
        case (.string(let a), .string(let b)):       return a == b
        case (.array(let a), .array(let b)):         return a == b
        case (.dictionary(let a), .dictionary(let b)): return a == b
        default:                                     return false
        }
    }
}

// MARK: - Bridge from AnyCodable

extension AnyCodableValue {

    /// Convert a raw `Any` value (from AnyCodable.value) into an AnyCodableValue.
    /// Bool is checked before Int/Double to avoid NSNumber false positives.
    static func from(_ value: Any) -> AnyCodableValue {
        switch value {
        case is NSNull:
            return .null
        case let bool as Bool:
            return .bool(bool)
        case let int as Int:
            return .int(int)
        case let double as Double:
            return .double(double)
        case let string as String:
            return .string(string)
        case let array as [Any]:
            return .array(array.map { AnyCodableValue.from($0) })
        case let dict as [String: Any]:
            return .dictionary(dict.mapValues { AnyCodableValue.from($0) })
        default:
            return .string(String(describing: value))
        }
    }

    /// Convenience: convert an AnyCodable directly.
    static func from(_ codable: AnyCodable) -> AnyCodableValue {
        from(codable.value)
    }
}

// MARK: - Hashable

extension AnyCodableValue: Hashable {
    func hash(into hasher: inout Hasher) {
        switch self {
        case .null:
            hasher.combine(0)
        case .bool(let value):
            hasher.combine(1)
            hasher.combine(value)
        case .int(let value):
            hasher.combine(2)
            hasher.combine(value)
        case .double(let value):
            hasher.combine(3)
            hasher.combine(value)
        case .string(let value):
            hasher.combine(4)
            hasher.combine(value)
        case .array(let value):
            hasher.combine(5)
            hasher.combine(value)
        case .dictionary(let dict):
            hasher.combine(6)
            for key in dict.keys.sorted() {
                hasher.combine(key)
                hasher.combine(dict[key]!)
            }
        }
    }
}
