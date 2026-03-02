import Foundation

// MARK: - ApprovalAction

/// Maps to shared/types/approvals.ts → ApprovalAction
enum ApprovalAction: String, Codable, CaseIterable, Equatable {
    case submit
    case pay
    case send
    case delete
    case sharePersonalInfo = "share_personal_info"

    var displayName: String {
        switch self {
        case .submit: "Submit"
        case .pay: "Pay"
        case .send: "Send"
        case .delete: "Delete"
        case .sharePersonalInfo: "Share Personal Info"
        }
    }

    var iconName: String {
        switch self {
        case .submit: "paperplane.fill"
        case .pay: "creditcard.fill"
        case .send: "arrow.up.circle.fill"
        case .delete: "trash.fill"
        case .sharePersonalInfo: "person.badge.shield.checkmark.fill"
        }
    }

    /// Color name string — view layer maps to SwiftUI Color
    var iconColor: String {
        switch self {
        case .submit: "blue"
        case .pay: "green"
        case .send: "indigo"
        case .delete: "red"
        case .sharePersonalInfo: "orange"
        }
    }

    var isDestructive: Bool {
        switch self {
        case .pay, .delete: true
        default: false
        }
    }
}

// MARK: - ApprovalDecision

/// Maps to shared/types/approvals.ts → ApprovalDecision
enum ApprovalDecision: String, Codable, Equatable {
    case approved
    case denied

    var displayName: String {
        switch self {
        case .approved: "Approved"
        case .denied: "Denied"
        }
    }
}

// MARK: - ApprovalRequest

/// Full approval request — maps to shared/types/approvals.ts → ApprovalRequest
/// Uses [String: String] for `details` (simplified from backend's Record<string, unknown> for Codable friendliness)
struct ApprovalRequest: Identifiable, Codable, Equatable {
    let id: String
    let taskId: String
    let action: ApprovalAction
    let description: String
    let details: [String: String]
    /// ISO 8601
    let createdAt: String

    var createdDate: Date? {
        ISO8601DateFormatter().date(from: createdAt)
    }

    var timeAgo: String {
        guard let date = createdDate else { return "" }
        let seconds = Int(Date().timeIntervalSince(date))
        if seconds < 60 { return "just now" }
        let minutes = seconds / 60
        if minutes < 60 { return "\(minutes)m ago" }
        let hours = minutes / 60
        if hours < 24 { return "\(hours)h ago" }
        let days = hours / 24
        return "\(days)d ago"
    }
}

// MARK: - ApprovalResponse

/// Decision record — maps to shared/types/approvals.ts → ApprovalResponse
struct ApprovalResponse: Identifiable, Codable, Equatable {
    let id: String
    let decision: ApprovalDecision
    /// ISO 8601
    let decidedAt: String

    var decidedDate: Date? {
        ISO8601DateFormatter().date(from: decidedAt)
    }
}

// MARK: - ResolvedApproval

/// Combined request + response for history display
struct ResolvedApproval: Identifiable, Codable, Equatable {
    let request: ApprovalRequest
    let response: ApprovalResponse

    var id: String { request.id }
}

// MARK: - Mocks

extension ApprovalRequest {
    static let mockSubmit = ApprovalRequest(
        id: "approval-101",
        taskId: "task-003",
        action: .submit,
        description: "Submit rental application for 245 Bedford Ave #4A",
        details: [
            "property": "245 Bedford Ave #4A, Brooklyn NY",
            "monthly_rent": "$3,200",
            "move_in": "2026-04-01",
        ],
        createdAt: "2026-02-28T14:00:00Z"
    )

    static let mockPay = ApprovalRequest(
        id: "approval-102",
        taskId: "task-003",
        action: .pay,
        description: "Book United UA 456 SFO→JFK for $389",
        details: [
            "airline": "United Airlines",
            "flight": "UA 456",
            "route": "SFO → JFK",
            "price": "$389",
            "card": "Visa ending 4242",
        ],
        createdAt: "2026-02-28T14:05:00Z"
    )

    static let mockSend = ApprovalRequest(
        id: "approval-103",
        taskId: "task-005",
        action: .send,
        description: "Send signed lease to landlord via email",
        details: [
            "recipient": "landlord@example.com",
            "attachment": "lease_signed.pdf",
        ],
        createdAt: "2026-02-28T14:10:00Z"
    )

    static let mockDelete = ApprovalRequest(
        id: "approval-104",
        taskId: "task-006",
        action: .delete,
        description: "Cancel and delete existing flight reservation AA 123",
        details: [
            "reservation": "AA 123",
            "refund": "$275 to Visa ending 4242",
        ],
        createdAt: "2026-02-28T14:15:00Z"
    )

    static let mockSharePersonalInfo = ApprovalRequest(
        id: "approval-105",
        taskId: "task-007",
        action: .sharePersonalInfo,
        description: "Share SSN and income verification with rental agency",
        details: [
            "agency": "Brooklyn Realty Group",
            "fields_shared": "SSN, annual income, employer",
        ],
        createdAt: "2026-02-28T14:20:00Z"
    )

    static let allMocks: [ApprovalRequest] = [
        .mockSubmit, .mockPay, .mockSend, .mockDelete, .mockSharePersonalInfo,
    ]
}

extension ApprovalResponse {
    static let mockApproved = ApprovalResponse(
        id: "approval-102",
        decision: .approved,
        decidedAt: "2026-02-28T14:06:00Z"
    )

    static let mockDenied = ApprovalResponse(
        id: "approval-104",
        decision: .denied,
        decidedAt: "2026-02-28T14:16:00Z"
    )
}

extension ResolvedApproval {
    static let mockApproved = ResolvedApproval(
        request: .mockPay,
        response: .mockApproved
    )

    static let mockDenied = ResolvedApproval(
        request: .mockDelete,
        response: .mockDenied
    )
}
