import Foundation

// MARK: - MessageRole

enum MessageRole: String, Codable, CaseIterable {
    case user
    case assistant
}

// MARK: - ChatMessage
// Client-local model — uses Date for timestamp since it's never sent over the wire raw.

struct ChatMessage: Identifiable, Codable, Equatable {
    let id: UUID
    let role: MessageRole
    var content: String
    let timestamp: Date
    var isStreaming: Bool

    init(
        id: UUID = UUID(),
        role: MessageRole,
        content: String,
        timestamp: Date = Date(),
        isStreaming: Bool = false
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.isStreaming = isStreaming
    }

    /// Factory for an empty assistant message that will be filled by streaming deltas.
    static func assistantPlaceholder() -> ChatMessage {
        ChatMessage(role: .assistant, content: "", isStreaming: true)
    }
}
