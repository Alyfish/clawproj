import Foundation

// MARK: - TaskStatus
// Maps to shared/types/tasks.ts → TaskStatus

enum TaskStatus: String, Codable, CaseIterable {
    case planning
    case searching
    case waitingInput = "waiting_input"
    case waitingApproval = "waiting_approval"
    case executing
    case monitoring
    case completed
    case stopped

    var displayName: String {
        switch self {
        case .planning:         return "Planning"
        case .searching:        return "Searching"
        case .waitingInput:     return "Waiting for Input"
        case .waitingApproval:  return "Waiting for Approval"
        case .executing:        return "Executing"
        case .monitoring:       return "Monitoring"
        case .completed:        return "Completed"
        case .stopped:          return "Stopped"
        }
    }

    var isActive: Bool {
        switch self {
        case .planning, .searching, .waitingInput, .waitingApproval, .executing, .monitoring:
            return true
        case .completed, .stopped:
            return false
        }
    }
}

// MARK: - AgentTask
// Maps to shared/types/tasks.ts → Task
// Named AgentTask to avoid collision with Swift.Task

struct AgentTask: Identifiable, Codable, Equatable, Hashable {
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: AgentTask, rhs: AgentTask) -> Bool { lhs.id == rhs.id && lhs.updatedAt == rhs.updatedAt }

    let id: String
    var status: TaskStatus
    let goal: String
    var steps: [ThinkingStep]
    var cardIds: [String]
    var approvalIds: [String]
    /// ISO 8601
    let createdAt: String
    /// ISO 8601
    var updatedAt: String

    // MARK: - Computed

    var createdDate: Date? {
        ISO8601DateFormatter().date(from: createdAt)
    }

    var updatedDate: Date? {
        ISO8601DateFormatter().date(from: updatedAt)
    }

    var completedStepCount: Int {
        steps.filter { $0.status == .done }.count
    }
}

// MARK: - PendingApproval
// Maps to shared/types/approvals.ts → ApprovalRequest (lightweight client model)

struct PendingApproval: Identifiable, Codable, Equatable {
    let id: String
    let taskId: String
    let action: String
    let description: String
    /// ISO 8601
    let createdAt: String
}

// MARK: - Mocks

extension AgentTask {
    static let mock = AgentTask(
        id: "task-001",
        status: .completed,
        goal: "Find the cheapest round-trip flight from SFO to JFK next weekend",
        steps: [
            ThinkingStep(id: "s1", description: "Searching flights", status: .done, toolName: "flight_search", timestamp: "2026-02-28T10:00:00Z"),
            ThinkingStep(id: "s2", description: "Comparing prices", status: .done, timestamp: "2026-02-28T10:01:00Z"),
            ThinkingStep(id: "s3", description: "Ranking results", status: .done, timestamp: "2026-02-28T10:02:00Z"),
        ],
        cardIds: ["card-f1", "card-f2", "card-f3"],
        approvalIds: [],
        createdAt: "2026-02-28T10:00:00Z",
        updatedAt: "2026-02-28T10:02:00Z"
    )

    static let mockSearching = AgentTask(
        id: "task-002",
        status: .searching,
        goal: "Find 2BR apartments in Williamsburg under $3,500/mo",
        steps: [
            ThinkingStep(id: "s1", description: "Setting up search filters", status: .done, timestamp: "2026-02-28T11:00:00Z"),
            ThinkingStep(id: "s2", description: "Scanning listings", status: .running, toolName: "apartment_search", timestamp: "2026-02-28T11:01:00Z"),
        ],
        cardIds: [],
        approvalIds: [],
        createdAt: "2026-02-28T11:00:00Z",
        updatedAt: "2026-02-28T11:01:00Z"
    )

    static let mockAwaitingApproval = AgentTask(
        id: "task-003",
        status: .waitingApproval,
        goal: "Book United flight UA 456 for $389",
        steps: [
            ThinkingStep(id: "s1", description: "Found flight", status: .done, timestamp: "2026-02-28T12:00:00Z"),
            ThinkingStep(id: "s2", description: "Ready to book — awaiting approval", status: .running, timestamp: "2026-02-28T12:01:00Z"),
        ],
        cardIds: ["card-f1"],
        approvalIds: ["approval-001"],
        createdAt: "2026-02-28T12:00:00Z",
        updatedAt: "2026-02-28T12:01:00Z"
    )

    static let mockStopped = AgentTask(
        id: "task-004",
        status: .stopped,
        goal: "Monitor Lakers -3.5 spread for line movement",
        steps: [
            ThinkingStep(id: "s1", description: "Monitoring stopped by user", status: .error, timestamp: "2026-02-28T13:00:00Z"),
        ],
        cardIds: ["card-p1"],
        approvalIds: [],
        createdAt: "2026-02-28T13:00:00Z",
        updatedAt: "2026-02-28T13:05:00Z"
    )
}

extension PendingApproval {
    static let mock = PendingApproval(
        id: "approval-001",
        taskId: "task-003",
        action: "book_flight",
        description: "Book United UA 456 SFO→JFK for $389",
        createdAt: "2026-02-28T12:01:00Z"
    )
}
