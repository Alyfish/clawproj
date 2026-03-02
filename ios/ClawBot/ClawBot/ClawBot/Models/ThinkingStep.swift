import Foundation

// MARK: - ThinkingStepStatus
// Maps to shared/types/tasks.ts → ThinkingStep.status

enum ThinkingStepStatus: String, Codable, CaseIterable {
    case pending
    case running
    case done
    case error
}

// MARK: - ThinkingStep
// Maps to shared/types/tasks.ts → ThinkingStep

struct ThinkingStep: Identifiable, Codable, Equatable {
    let id: String
    let description: String
    var status: ThinkingStepStatus
    let toolName: String?
    let result: String?
    /// ISO 8601 string — matches backend convention.
    let timestamp: String

    init(
        id: String,
        description: String,
        status: ThinkingStepStatus = .pending,
        toolName: String? = nil,
        result: String? = nil,
        timestamp: String
    ) {
        self.id = id
        self.description = description
        self.status = status
        self.toolName = toolName
        self.result = result
        self.timestamp = timestamp
    }
}
