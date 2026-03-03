import Foundation

// MARK: - StreamEvent
// Maps to shared/types/gateway.ts → StreamEvent discriminated union.
// Swift enum with associated values — parsed manually from WSMessage, not Codable.

enum StreamEvent {
    /// Token-by-token assistant text delta.
    case assistantDelta(delta: String)
    /// Agent run lifecycle boundary.
    case lifecycle(status: String, runId: String)
    /// Thinking step update from agent.
    case stateDelta(step: ThinkingStep)
    /// Task status + optional step update.
    case taskUpdate(taskId: String, status: String, step: ThinkingStep?)
    /// Action requires user approval before execution.
    case approvalRequested(
        id: String, taskId: String, action: String,
        description: String, details: [String: AnyCodable]
    )
    /// Tool execution started.
    case toolStarted(toolName: String, description: String)
    /// Tool execution completed.
    case toolCompleted(toolName: String, success: Bool, summary: String)
    /// Structured card created by agent.
    case cardCreated(card: [String: AnyCodable])
    /// Unrecognised event name — forward-compatible.
    case unknown(event: String, payload: [String: AnyCodable]?)

    // MARK: Parser

    static func from(_ message: WSMessage) -> StreamEvent? {
        guard message.type == .event, let eventName = message.event else {
            return nil
        }
        let p = message.payload

        switch eventName {

        case "agent/stream:assistant":
            guard let delta = p?["delta"]?.stringValue else { return nil }
            return .assistantDelta(delta: delta)

        case "agent/stream:lifecycle":
            guard
                let status = p?["status"]?.stringValue,
                let runId = p?["runId"]?.stringValue
            else { return nil }
            return .lifecycle(status: status, runId: runId)

        case "chat/state:delta":
            // Preferred: nested thinkingStep object (real agent format)
            if let step = decodeStep(from: p?["thinkingStep"]) {
                return .stateDelta(step: step)
            }
            // Fallback: flat { toolName, summary } (test-client compat)
            guard
                let toolName = p?["toolName"]?.stringValue,
                let summary = p?["summary"]?.stringValue
            else { return nil }
            return .stateDelta(step: ThinkingStep(
                id: UUID().uuidString,
                description: summary,
                status: .running,
                toolName: toolName,
                timestamp: ISO8601DateFormatter().string(from: Date())
            ))

        case "task/update":
            guard
                let taskId = p?["taskId"]?.stringValue,
                let status = p?["status"]?.stringValue
            else { return nil }
            let step = decodeStep(from: p?["step"])
            return .taskUpdate(taskId: taskId, status: status, step: step)

        case "approval/requested":
            guard
                let id = p?["id"]?.stringValue,
                let taskId = p?["taskId"]?.stringValue,
                let action = p?["action"]?.stringValue,
                let description = p?["description"]?.stringValue
            else { return nil }
            let details = decodeDetails(from: p?["details"])
            return .approvalRequested(
                id: id, taskId: taskId, action: action,
                description: description, details: details
            )

        case "agent/tool:start":
            guard
                let toolName = p?["toolName"]?.stringValue,
                let description = p?["description"]?.stringValue
            else { return nil }
            return .toolStarted(toolName: toolName, description: description)

        case "agent/tool:end":
            guard
                let toolName = p?["toolName"]?.stringValue,
                let summary = p?["summary"]?.stringValue
            else { return nil }
            let success = p?["success"]?.boolValue ?? false
            return .toolCompleted(toolName: toolName, success: success, summary: summary)

        case "card/created":
            guard let card = p?["card"]?.dictValue else { return nil }
            return .cardCreated(card: card.mapValues { AnyCodable($0) })

        default:
            return .unknown(event: eventName, payload: p)
        }
    }

    // MARK: - Private helpers

    private static func decodeStep(from value: AnyCodable?) -> ThinkingStep? {
        guard let dict = value?.dictValue else { return nil }
        guard
            let id = dict["id"] as? String,
            let description = dict["description"] as? String,
            let statusRaw = dict["status"] as? String,
            let status = ThinkingStepStatus(rawValue: statusRaw),
            let timestamp = dict["timestamp"] as? String
        else { return nil }
        return ThinkingStep(
            id: id,
            description: description,
            status: status,
            toolName: dict["toolName"] as? String,
            result: dict["result"] as? String,
            timestamp: timestamp
        )
    }

    private static func decodeDetails(from value: AnyCodable?) -> [String: AnyCodable] {
        guard let dict = value?.dictValue else { return [:] }
        return dict.mapValues { AnyCodable($0) }
    }
}
